#!/bin/bash

# Check if the environment.yml file exists
if [ -f environment.yml ]; then
    # Use awk to modify the dependencies
    awk '
    BEGIN {
        FS = "=";  # Set the field separator to "="
        OFS = "=";  # Set the output field separator to "="
    }
    
    $1 && $2 {
        $0 = $1 OFS $2;  # Reassemble the line with only the first two fields
    }
    
    { print }
    ' environment.yml > temp_environment.yml

    # Rename the modified file back to environment.yml
    mv temp_environment.yml environment.yml

    echo "Modified environment.yml file."
else
    echo "environment.yml file not found."
fi
