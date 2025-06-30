#!/bin/bash

# This script activates the Python virtual environment.

# The script must be run using 'source' for it to affect the current shell.
# Example: source activate.sh

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
  echo "Virtual environment activated."
else
  echo "Error: Virtual environment not found."
  echo "Please run the setup.sh script first to create it."
fi 