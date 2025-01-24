import os
import json
import asyncio
from bleak import BleakScanner, BleakClient
from pycycling.fitness_machine_service import FitnessMachineService

# THIS SCRIPT NEEDS TO BE RUN AT LEAST ONCE BEFORE RUNNING THE TRAINER DATA SCRIPT PLEASE


debug = 0

# Initialise the User Profile json
user_profile = "userprofile.json"

# Function to load profile
def load_profile():
    if os.path.exists(user_profile):
        with open(user_profile, "r") as f:
            try:
                profile = json.load(f)
                # Setting up the headings if they do not exist
                if "user_data" not in profile:
                    profile["user_data"] = {}
                if "device" not in profile:
                    profile["device"] = {}
                return profile
            except json.JSONDecodeError:
                return {"user_data": {}, "device": {}}
                # Return empty. This happens if the file is there but does not contain anything
    else:
        return {"user_data": {}, "device": {}}

# Function to save user profile
def save_profile(profile):
    with open(user_profile, "w") as f:
        json.dump(profile, f, indent=4, sort_keys=True)



# Username
def username_init():
    # Load up the existing profile
    profile = load_profile()

    # Check if the username exists in the profile and check its length
    if "username" in profile["user_data"]:
        if len(profile["user_data"]["username"]) > 24:
            print("Saved username is too long, please use another.")
            del profile["user_data"]["username"]  # Remove the invalid username from the profile
        else:
            # Welcome back the user, if the username is valid
            print(f"Welcome back, {profile["user_data"]['username']}!")
            return profile

    # Prompt for username if it's not there or invalid
    while True:
        username = input("Please enter your username (max 24 characters): ")
        if len(username) <= 24:
            profile["user_data"]["username"] = username
            save_profile(profile)
            break
        else:
            print("Username is too long. Please enter a username with 24 characters or fewer.")

    return profile

# Starting Difficulty. Setting this to 50% to mimic zwift functionality for now.
def difficulty_init(profile):
    # Add difficulty if it's not present in `user_data`
    if "difficulty" not in profile["user_data"]:
        profile["user_data"]["difficulty"] = 50

    # Set the baseline if it's not in user_data, to 20
    if "baseline" not in profile["user_data"]:
        profile["user_data"]["baseline"] = 20
    # If the user has changed their data, then it clamps it down to 24, or up to 18. I don't mind the user editing this
    # value themselves, but it has to be kept within boundaries, otherwise the program will be sorta pointless. Clamping
    # it to within 18-24% of the max resistance value makes sense to me. Subject to change, ofc.
    elif profile["user_data"]["baseline"] > 24:
        profile["user_data"]["baseline"] = 24
    elif profile["user_data"]["baseline"] < 18:
        profile["user_data"]["baseline"] = 18

    # Save the profile
    save_profile(profile)
    return profile



# Set the weight. I've clamped values between 30-200 in order to make it reasonable.
def weight_init(profile):
    if "weight" not in profile["user_data"]:
        try:
            weight = float(input("Enter your weight in kilograms (default is 70kg): ") or 70.0)
            profile["user_data"]["weight"] = max(30.0, min(200.0, weight))  # Clamp to a range (30kg - 200kg)
        except ValueError:
            print("Invalid input. Setting weight to default value of 70kg.")
            profile["user_data"]["weight"] = 70.0
        save_profile(profile)
    return profile


# Check FTMS Power Support
# As power is the most basic first step in cycling trainers, this check will ensure that the device is at least
# compatible with power output, before proceeding with the program. In theory, if the script is well designed, we can
# work with power alone, and ignore other metrics.
async def check_ftms_power_support(client):
    try:
        ftms = FitnessMachineService(client)
        features_tuple = await ftms.get_fitness_machine_feature()
        fitness_features = features_tuple[0]

        # Check for power measurement
        if fitness_features.power_measurement_supported:
            return True
        else:
            return False

    # Exception Handling
    except Exception as e:
        print(f"Error querying FTMS services: {e}")
        return False

# Query FTMS Features
# This query retrieves and categorizes FTMS features into supported and unsupported.
async def query_ftms_features(client):
    try:
        ftms = FitnessMachineService(client)
        features_tuple = await ftms.get_fitness_machine_feature()
        fitness_features = features_tuple[0]  # First element of the tuple

        # Sorrt fitness machine features into True and False
        true_features = [
            field for field in fitness_features._fields if getattr(fitness_features, field)
        ]
        false_features = [
            field for field in fitness_features._fields if not getattr(fitness_features, field)
        ]

        return true_features, false_features

    except Exception as e:
        print(f"Error querying FTMS features: {e}")
        return [], []


# Function for establishing a connection with the heart rate monitor (HRM)
async def connect_hrm(profile):

    # Check if there's an HRM already saved in the profile
    if "hrm_name" in profile["device"] and "hrm_address" in profile["device"]:
        print(f"HRM already saved: {profile['device']['hrm_name']}")
        return  # Skip connection if HRM is already saved

    # Begin scanning for HRM devices
    print("Searching for heart rate monitors...")
    devices = await BleakScanner.discover()

    # If there are no devices found nearby, print a message to the user
    if not devices:
        print("No devices found. Please make sure your HRM is on and discoverable.")
        return

    # Show the local devices, with indices for selection
    for i, device in enumerate(devices):
        print(f"{i}: {device.name if device.name else 'Unknown Device'}")

    # Allow the user to select an HRM device
    try:
        device_index = int(input("Select the HRM device index to save:"))
        selected_device = devices[device_index]

        # Attempt to connect to the selected HRM
        async with BleakClient(selected_device.address) as client:
            if client.is_connected:
                print(f"Connected to HRM: {selected_device.name}")

                # Save the HRM details to the profile
                profile["device"]["hrm_name"] = selected_device.name
                profile["device"]["hrm_address"] = selected_device.address
                save_profile(profile)
                print(f"HRM saved. Name: {profile['device']['hrm_name']}, Address: {profile['device']['hrm_address']}")

                return
            else:
                print("Failed to connect to the selected HRM.")
    except (ValueError, IndexError):
        print("Invalid selection. Please try again.")
        return await connect_hrm(profile)
    except Exception as e:
        print(f"Error connecting to the selected HRM: {e}")
        return await connect_hrm(profile)

# Function for Establishing a connection with the trainer
async def connect_device(profile):

    # Check if there's a device already saved in the profile
    if "device" in profile and "name" in profile["device"] and "address" in profile["device"]:
        print(f"Device already saved: {profile['device']['name']}")
        device_name = profile["device"]["name"]
        device_address = profile["device"]["address"]

        # Check if compatibility flags exist
        if all(flag in profile["device"] for flag in ["power", "cadence"]):
            print("Compatibility already checked.")
            print(f"Power: {profile['device']['power']}, Cadence: {profile['device']['cadence']}, Speed: {profile['device'].get('speed', 'N/A')}")
            return  # Skip compatibility check if required flags exist

        # Attempt to connect to the saved device
        try:
            async with BleakClient(device_address) as client:
                if client.is_connected:
                    print("Connected to the saved device.")

                    # Query FTMS features and save compatibility flags
                    true_features, _ = await query_ftms_features(client)
                    profile["device"]["power"] = "power_measurement_supported" in true_features
                    profile["device"]["cadence"] = "cadence_supported" in true_features
                    profile["device"]["speed"] = "avg_speed_supported" in true_features # THIS IS OPTIONAL

                    # Check compatibility
                    if profile["device"]["power"] and profile["device"]["cadence"]:
                        save_profile(profile)
                        print(f"Device is compatible. Power: {profile['device']['power']}, Cadence: {profile['device']['cadence']}, Speed: {profile['device']['speed']}")
                    else:
                        print("Device is not compatible. Power and Cadence are required features.")
                        del profile["device"]
                        save_profile(profile)

                    return
                else:
                    print("Failed to connect to the saved device.")
        except Exception:
            print("Error connecting to the saved device. Removing from profile.")
            del profile["device"]
            save_profile(profile)
            return await connect_device(profile)  # Restart selection

    # If no device is saved, begin scanning for devices
    print("Searching for devices...")
    devices = await BleakScanner.discover()

    # If there are no devices found nearby, print a message to the user
    if not devices:
        print("No devices found. Please make sure your trainer is on and discoverable.")
        return

    # Show the local devices, with their indices for selection
    for i, device in enumerate(devices):
        print(f"{i}: {device.name if device.name else 'Unknown Device'}")

    # Allow the user to select a device
    try:
        device_index = int(input("Select the device index to save:"))
        selected_device = devices[device_index]

        # Attempt to connect to the selected device
        async with BleakClient(selected_device.address) as client:
            if client.is_connected:
                print("Connected to the selected device.")

                # Query FTMS features and save compatibility flags
                true_features, _ = await query_ftms_features(client)
                profile["device"] = {
                    "name": selected_device.name,
                    "address": selected_device.address,
                    "power": "power_measurement_supported" in true_features,
                    "cadence": "cadence_supported" in true_features,
                    "speed": "avg_speed_supported" in true_features,  # Optional feature
                }

                # Check compatibility
                if profile["device"]["power"] and profile["device"]["cadence"]:
                    save_profile(profile)
                    print(f"Device saved. Power: {profile['device']['power']}, Cadence: {profile['device']['cadence']}, Speed: {profile['device']['speed']}")
                else:
                    print("Device is not compatible. Power and Cadence are required features.")
                    del profile["device"]
                    save_profile(profile)

                return
            else:
                print("Failed to connect to the selected device.")
    except (ValueError, IndexError):
        print("Invalid selection. Please try again.")
        return await connect_device(profile)
    except Exception:
        print("Error connecting to the selected device. Please try again.")
        return await connect_device(profile)

# Establishing a connection with the device.
# This function now only maintains a connection to the device already validated.
async def establish_connection(profile):
    if "device" not in profile:
        print("No saved devices found.")
        return

    device_name = profile["device"]["name"]
    device_address = profile["device"]["address"]

    print(f"Attempting to connect to {device_name}...")

    try:
        async with BleakClient(device_address) as client:
            if client.is_connected:
                print(f"Successfully connected to {device_name}.")
                print("Press Ctrl+C to end the connection.")
                while True:
                    await asyncio.sleep(0.5)  # Keeps the connection alive
            else:
                print(f"Failed to connect to {device_name}.")
    except Exception as e:
        print(f"Error while connecting to {device_name}: {e}")

# Main loop of program
if __name__ == "__main__":
    profile = username_init()
    difficulty_init(profile)
    weight_init(profile)
    asyncio.run(connect_device(profile))    # trainer
    asyncio.run(connect_hrm(profile))       # hrm
