# Clone repository
git clone https://github.com/Qualcomm-AI-research/gauge-equivariant-mesh-cnn

# Move def file and launch build
mv gauge-equivariant-mesh-cnn.def gauge-equivariant-mesh-cnn/
cd gauge-equivariant-mesh-cnn/
sudo apptainer build ../gauge-equivariant-mesh-cnn.sif gauge-equivariant-mesh-cnn.def

# Delete all not SIF files, so only image file is offloaded
cd ..
find . -type f -not -name 'gauge-equivariant-mesh-cnn.sif' -delete