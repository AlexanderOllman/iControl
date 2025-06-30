#!/bin/bash

# This script creates a virtual environment and installs the required packages.

# Check if python3 is available
if ! command -v python3 &> /dev/null
then
    echo "python3 could not be found. Please install Python 3."
    exit
fi

# Create a virtual environment in a .venv directory
echo "Creating virtual environment..."
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Install the required packages
echo "Installing requirements from requirements.txt..."
pip install -r requirements.txt

echo ""
echo "Setup complete. The virtual environment is created and packages are installed."
echo "Run 'source .venv/bin/activate' to activate the environment in your terminal." 