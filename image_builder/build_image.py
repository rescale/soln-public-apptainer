"""Apptainer Image Builder
"""

import argparse
import logging
import sys
import os
import time
import json
from typing import List, NamedTuple

import requests

BASE_HOST = "eu.rescale.com"
ANALYSIS_CODE = "user_included_apptainer_container"
ANALYSIS_VERSION = "1.0.1"
CORETYPE = "emerald"
CORE_COUNT = 2
WALLTIME = 2

log = logging.getLogger(__name__)


class JobSpec(NamedTuple):
    """Parameter holder for job related properties"""

    name: str
    deffile_path: str
    buildscript_path: str
    project: str
    analysis_code: str
    analysis_version: str
    coretype: str
    core_count: int
    walltime: int


class ApiSpec(NamedTuple):
    """Parameter holder for API related properties"""

    basehost: str
    apikey: str


def _init_logging():
    logging.getLogger().handlers = []
    detailed_formatter = logging.Formatter("%(asctime)s: %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(detailed_formatter)

    log.setLevel(logging.INFO)
    log.addHandler(console_handler)


def _upload_file(filepath: str, apikey: str, basehost: str):
    with open(filepath, "rb") as file:
        response = requests.post(
            f"https://{basehost}/api/v2/files/contents/",
            headers={
                "Authorization": f"Token {apikey}"
            },
            data={},
            files=[
                (
                    "file",
                    (
                        os.path.basename(filepath),
                        file,
                        "application/octet-stream",
                    ),
                )
            ],
        )
        response.raise_for_status()
    file_id = response.json()["id"]

    log.info("Successfully uploaded file with id = %s", file_id)
    return file_id


def _create_build_job(file_ids: List[str], jobspec: JobSpec, apispec: ApiSpec):
    log.info("Creating a job")

    jobspec_json = {
        "name": jobspec.name,
        "description": "Apptainer Image Build Job",
        "jobanalyses": [
            {
                "analysis": {
                    "code": jobspec.analysis_code,
                    "version": jobspec.analysis_version,
                },
                "command": f"sh {os.path.basename(jobspec.buildscript_path)}",
                "hardware": {
                    "coresPerSlot": jobspec.core_count,
                    "slots": 1,
                    "walltime": jobspec.walltime,
                    "type": "compute",
                    "coreType": jobspec.coretype,
                },
                "inputFiles": [{"id": id} for id in file_ids],
            }
        ],
    }
    response = requests.post(
        f"https://{apispec.basehost}/api/v2/jobs/",
        data=json.dumps(jobspec_json, indent=2),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {apispec.apikey}",
        },
    )
    response.raise_for_status()
    job_id = response.json()["id"]

    log.info("Successfully created a job with id = %s", job_id)
    return job_id


def _submit_build_job(job_id: str, apispec: ApiSpec):
    log.info("Submitting job id = %s", job_id)

    response = requests.post(
        f"https://{apispec.basehost}/api/v2/jobs/{job_id}/submit/",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {apispec.apikey}",
        },
    )
    response.raise_for_status()


def _monitor_job(job_id: str, apispec: ApiSpec, status_poll_sleep: int = 30):
    while True:
        response = requests.get(
            f"https://{apispec.basehost}/api/v2/jobs/{job_id}/statuses/",
            headers={"Authorization": f"Token {apispec.apikey}"},
        )
        response.raise_for_status()
        job_status = response.json()["results"][0]

        # It takes a while before cluster statuses are available
        while True:
            response = requests.get(
                f"https://{apispec.basehost}/api/v2/jobs/{job_id}/cluster_statuses/",
                headers={"Authorization": f"Token {apispec.apikey}"},
            )
            if response.status_code == 404:
                time.sleep(5)
            else:
                break

        response.raise_for_status()
        cluster_status = response.json()["results"][0]

        log.info("Status (job): %s", job_status["status"])
        log.info("Status (cluster): %s", cluster_status["status"])

        if job_status["status"] == "Completed":
            log.info("Job %s completed", job_id)
            break

        time.sleep(status_poll_sleep)


def _link_outfile_with_folder(job_id: str, apispec: ApiSpec):
    images_folder_name = "apptainer_images"

    response = requests.get(
        f"https://{apispec.basehost}/api/v2/jobs/{job_id}/files/?search=sif",
        headers={"Authorization": f"Token {apispec.apikey}"},
    )
    response.raise_for_status()
    files = response.json()["results"]
    if len(files) != 1:
        log.info("A single matching .sif file expected")
        raise Exception()
    sif_file_id = response.json()["results"][0]["id"]

    # Get folders
    response = requests.get(
        f"https://{apispec.basehost}/api/v3/file-folders/",
        headers={"Authorization": f"Token {apispec.apikey}"},
    )
    response.raise_for_status()
    folders = response.json()
    images_folder = [f for f in folders if f["name"] == images_folder_name]

    if len(images_folder) == 0: 
        # Create folder
        response = requests.post(
            f"https://{apispec.basehost}/api/v3/file-folders/",
            json={"name": images_folder_name, "parentId": None},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token {apispec.apikey}",
            },
        )
        # Ignore folder exists 400
        if response.status_code not in (201, 400):
            response.raise_for_status()
        folder_id = response.json()["id"]
    else:
        folder_id = images_folder[0]["id"]

    # Assign file to folder
    response = requests.post(
        f"https://{apispec.basehost}/api/v3/file-folders/{folder_id}/files/",
        json={"ids": [f"{sif_file_id}"]},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {apispec.apikey}",
        },
    )
    response.raise_for_status()

    # Tag file as input file
    response = requests.post(
        f"https://{apispec.basehost}/api/v3/files/bulk/type-change/",
        json={"ids": [f"{sif_file_id}"], "type": 1},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {apispec.apikey}",
        },
    )
    response.raise_for_status()


def _display_process_output(job_id: str, apispec: ApiSpec):
    response = requests.get(
        f"https://{apispec.basehost}/api/v2/jobs/{job_id}/files/"
        "?search=process_output&page=1&page_size=10",
        headers={"Authorization": f"Token {apispec.apikey}"},
    )
    response.raise_for_status()
    file_id = response.json()["results"][0]["id"]

    response = requests.get(
        f"https://{apispec.basehost}/api/v2/files/{file_id}/lines/",
        headers={"Authorization": f"Token {apispec.apikey}"},
    )
    response.raise_for_status()
    for line in response.json()["lines"]:
        print(line, end='')


def _build_image(jobspec: JobSpec, apispec: ApiSpec):
    file_ids = []
    for filepath in [jobspec.buildscript_path, jobspec.deffile_path]:
        file_id = _upload_file(filepath, apispec.apikey, apispec.basehost)
        file_ids.append(file_id)

    job_id = _create_build_job(file_ids, jobspec, apispec)
    _submit_build_job(job_id, apispec)
    _monitor_job(job_id, apispec)
    _link_outfile_with_folder(job_id, apispec)
    _display_process_output(job_id, apispec)


if __name__ == "__main__":
    _init_logging()

    all_args = argparse.ArgumentParser()

    all_args.add_argument("-k", "--apikey", required=True, help="Rescale API Key")
    all_args.add_argument(
        "-d", "--deffile", required=True, help="Apptainer Image definition file"
    )
    all_args.add_argument(
        "-s", "--buildscript", required=True, help="Image build script"
    )
    all_args.add_argument(
        "-n",
        "--jobname",
        required=True,
        default=None,
        help="Output name of the image sif file",
    )
    all_args.add_argument(
        "-p",
        "--project",
        required=False,
        help="Optional Project Id for Jobs that need to be charged against a "
        "specific project.",
    )

    args = vars(all_args.parse_args())

    _build_image(
        JobSpec(
            args["jobname"],
            args["deffile"],
            args["buildscript"],
            args["project"],
            ANALYSIS_CODE,
            ANALYSIS_VERSION,
            CORETYPE,
            CORE_COUNT,
            WALLTIME,
        ),
        ApiSpec(
            BASE_HOST,
            args["apikey"]
        ),
    )
