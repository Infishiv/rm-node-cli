import json

# Path to your binary input and JSON output files
input_bin_file = 'input.bin'
output_json_file = 'output.json'

# Step 1: Read binary content and decode
with open(input_bin_file, 'rb') as bin_file:
    binary_data = bin_file.read()
    json_str = binary_data.decode('utf-8')

# Step 2: Parse JSON string to Python object
try:
    json_data = json.loads(json_str)
except json.JSONDecodeError as e:
    print("Error decoding JSON:", e)
    exit(1)

# Step 3: Write to JSON file
with open(output_json_file, 'w', encoding='utf-8') as json_file:
    json.dump(json_data, json_file, indent=2)

print(f"Successfully converted {input_bin_file} to {output_json_file}")
