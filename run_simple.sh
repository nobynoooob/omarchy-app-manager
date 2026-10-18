#!/bin/bash

# OmaApp Manager - Simple Launcher Script

echo "OmaApp Manager"
echo "==================="

# Run the application directly with the virtual environment's python
source venv/bin/activate
cd /home/nobynoooob/Work/omarchy_app_manager
python3 -c "
import sys
sys.path.insert(0, 'src')

print('✓ Environment setup complete')
print('✓ OmaApp Manager starting...')
print('')
print('Note: If the application window doesn\'t appear,')
print('it may be starting in the background.')
print('')

from omarchy_app_manager.__main__ import main
main()
" 2>&1 | head -50
