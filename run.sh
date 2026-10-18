#!/bin/bash

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Add src to Python path
cd /home/nobynoooob/Work/omarchy_app_manager
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# Run the application
python3 -c "from omarchy_app_manager.__main__ import main; main()"
