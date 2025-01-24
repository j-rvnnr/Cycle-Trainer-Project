import asyncio
import json
import os
import time
import math
from pycycling.fitness_machine_service import FitnessMachineService
from bleak import BleakClient, BleakScanner
from connect_profile import load_profile

'''
To Do:
Fix acceleration
test on multiple hardware setups.

'''





# Initialising svariables and settings
debug = True
user_profile = "userprofile.json"
calculated_resistance = 30

# Create the shared data structure
def init_shared_data(profile_file):
    # function to load in the profile
    def load_profile(profile_file):
        if os.path.exists(profile_file):
            with open(profile_file, "r") as f:
                try:
                    profile = json.load(f)
                    # Setting up the headings, if they do not exist
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

    profile = load_profile(user_profile)

    # Extract device information
    settings = {
        "trainer_address": profile.get("device", {}).get("address", None),
        "trainer_name": profile.get("device", {}).get("name", None),
        "hrm_address": profile.get("device", {}).get("hrm_address", None),
        "hrm_name": profile.get("device", {}).get("hrm_name", None),
        "has_power": profile.get("device", {}).get("power", False),
        "has_cadence": profile.get("device", {}).get("cadence", False),
        "has_speed": profile.get("device", {}).get("speed", False),
        "base_resistance": profile.get("user_data", {}).get("baseline", 20),
        "difficulty": profile.get("user_data", {}).get("difficulty", 50),
        "weight": profile.get("user_data", {}).get("weight", 75),
    }

    shared_data = {
        "power": 0,
        "cadence": 0,
        "speed": 0,
        "heart_rate": None,
        "weight": settings["weight"]
    }

    debug_data = {}

    # debug for readout
    if debug:
        print("Shared Data Initialized:", shared_data)
        print("Settings Initialized:", settings)

    return shared_data, settings, debug_data

# Connect to the devices (trainer first, then others)
async def device_connection(devices):
    connected_clients = {}

    async def connect_to_device(address, name):
        try:
            print(f"Scanning for device: {name}...")
            device_list = await BleakScanner.discover()
            device = next((d for d in device_list if d.address == address and d.name == name), None)

            if not device:
                print(f"Device {name} not found.")
                return None

            print(f"Connecting to device: {name}.")
            client = BleakClient(device.address)
            await client.connect()

            if not client.is_connected:
                print(f"Failed to connect to device: {name}")
                return None

            print(f"Connected to device: {name}")
            return client
        except Exception as e:
            print(f"Error: {e}")
            return None

    # Prioritize connecting to the trainer, otherwise the trainer doesn't get picked up. I think this is a hardware
    # Issue on my end, but this is also pretty logical so it's probably fine.
    trainer = devices.get("trainer")
    if trainer:
        trainer_address, trainer_name = trainer
        trainer_client = await connect_to_device(trainer_address, trainer_name)
        if trainer_client:
            connected_clients["trainer"] = trainer_client
        else:
            print("Critical Error: Trainer connection failed. Exiting program.")
            return None

    # Connect to any other devices
    for device_type, (address, name) in devices.items():
        if device_type != "trainer" and address and name:
            client = await connect_to_device(address, name)
            if client:
                connected_clients[device_type] = client
            else:
                print(f"Error: could not connect to {name}")

    return connected_clients


# Manage the fitness machine service (ftms) for trainer and HRM
async def init_ftms(shared_data, debug_data, trainer_client, hrm_client=None):
    shared_data.update({
        "power": None,
        "cadence": None,
        "speed": None,
        "heart_rate": None,
    })

    def trainer_data_handler(data):
        shared_data["power"] = getattr(data, "instant_power", 0.0)
        shared_data["cadence"] = getattr(data, "instant_cadence", 0.0)
        debug_data["t_speed"] = getattr(data, "instant_speed", 0.0)

    async def enable_hrm_notifications(client):
        def hrm_data_handler(sender, data):
            if data:
                heart_rate = data[1] if len(data) > 1 else None
                shared_data["heart_rate"] = heart_rate

        try:
            await client.start_notify(
                "00002a37-0000-1000-8000-00805f9b34fb", hrm_data_handler # FTMS should work with my hrm natively, this
                # code shouldn't be needed. More work needed
            )
            print("HRM notifications enabled")
        except Exception as e:
            print(f"Error enabling HRM notifications: {e}")

    try:
        trainer_ftms = FitnessMachineService(trainer_client)
        trainer_ftms.set_indoor_bike_data_handler(trainer_data_handler)
        print("Trainer handler set")

        await trainer_ftms.enable_control_point_indicate()
        print("Control point notifications enabled")

        await trainer_ftms.enable_indoor_bike_data_notify()
        print("Trainer notifications enabled")

        hrm_ftms = None
        if hrm_client:
            hrm_ftms = FitnessMachineService(hrm_client)
            await enable_hrm_notifications(hrm_client)

        print("FTMS and HRM initialized successfully")
        return shared_data, debug_data, trainer_ftms, hrm_ftms,

    except Exception as e:
        print(f"Error initializing FTMS or HRM: {e}")
        return shared_data, debug_data, None, None






# Set up resistance for the trainer
async def set_resistance(ftms, desired_resistance, current_resistance, shared_data, retries=10, debug=False):

    '''
I'm unsure if it's an issue with my trainer, pycycling or my bluetooth connection, but the retries here are necessary
because sometimes the resistance just doesn't set. Not sure why, but attempting multiple times does seem to make it work

My trainer is a Wahoo Kickr Core, but it's zwift branded, and the firmware is delivered through zwift too, so it could
be a proprietary issue. If I had infinite money, I would test with a variety of trainers and hardware setups, but I don't,
so I can't
    '''

    # Update shared_data with the current and desired resistance levels
    shared_data["c_resistance"] = current_resistance
    shared_data["d_resistance"] = desired_resistance

    # Checks to see if a new resistance level has to be set
    if desired_resistance == current_resistance:
        return current_resistance

    # Main Process, This tries to set the resistance as long as we're below 'retries'
    for attempt in range(retries):
        try:
            # Clamp resistance level between 0 and 100
            desired_resistance = max(0, min(100, desired_resistance))
            shared_data["d_resistance"] = desired_resistance  # Update desired_resistance in shared_data
            if debug:
                print(f"Setting resistance level to {desired_resistance}% (Attempt {attempt + 1})...")

            # Request control of the trainer
            if debug:
                print("Requesting control...")
            control_response = await ftms.request_control()
            if debug:
                print(f"Control Point Response (Request Control): {control_response}")

            # Reset the trainer. Needed
            if debug:
                print("Resetting trainer...")
            reset_response = await ftms.reset()
            if debug:
                print(f"Control Point Response (Reset): {reset_response}")

            # Set the target resistance level
            if debug:
                print(f"Setting target resistance level to {desired_resistance}%...")
            resistance_response = await ftms.set_target_resistance_level(desired_resistance)
            if debug:
                print(f"Control Point Response (Set Resistance): {resistance_response}")

            if debug:
                print(f"Resistance successfully set to {desired_resistance}%.")
            shared_data["current_resistance"] = desired_resistance  # Update current_resistance in shared_data
            return desired_resistance

        except Exception as e:
            if debug:
                print(f"Error while setting resistance (Attempt {attempt + 1}): {e}")
            if attempt == retries - 1:
                if debug:
                    print("Max retries reached. Giving up.")
                raise  # Rethrow the exception after the final attempt

    # Return the last known resistance if all attempts fail
    return current_resistance


# Create Derived information

def derived_information(shared_data, debug_data, elapsed_start_time, is_moving, session_start_time, debug=False):
    """
    This function is made up of a number of sub-functions, which take the outputs of the trainer, and convert them into
    useful stats for cycling metrics. We should be able to put any number of features in here, but for now we only have
    the important ones.
    """

    def calculate_elapsed_time():

        def format_time(total_seconds):
            hours, remainder = divmod(int(total_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            centiseconds = int((total_seconds - int(total_seconds)) * 100)
            return f"{hours:02}:{minutes:02}:{seconds:02}.{centiseconds:02}"

        nonlocal elapsed_start_time, is_moving

        power = shared_data.get("power", 0) or 0
        cadence = shared_data.get("cadence", 0) or 0
        elapsed_time = shared_data.get("raw_elapsed_time", 0)  # Accumulated elapsed time

        if power > 0 or cadence > 0 or shared_data["velocity"] > 0:
            if not is_moving:
                is_moving = True
                elapsed_start_time = time.time()  # Start accumulating time
            elif elapsed_start_time:
                elapsed_time += time.time() - elapsed_start_time  # Add time since last start
                elapsed_start_time = time.time()  # Update start time
        elif is_moving:
            is_moving = False
            if elapsed_start_time:
                elapsed_time += time.time() - elapsed_start_time  # Add final elapsed period
                elapsed_start_time = None

        total_time = time.time() - session_start_time  # Total time since session start
        shared_data["elapsed_timer"] = format_time(elapsed_time)
        shared_data["raw_elapsed_time"] = elapsed_time  # Persist accumulated elapsed time
        shared_data["total_timer"] = format_time(total_time)

    def calculate_virtual_speed(delta_t=1):

        '''
        This is an insane formula, mostly ripped from a couple of blogs and papers, and with a little help from chat gpt
        to help make sense of it. Hopefully it's accurate, it gives a slightly lower speed readout than the speed metric
        recorded from the trainer, which feels like it's in line with a physics simulation, however I am not a physicist
        so it could be totally off. Additionally, the acceleration and deceleration don't work properly. Another thing
        to add to the list of things to do.
        '''

        g = 9.8  # gravitational constant
        C_r = 0.006  # rolling resistance coefficient
        C_d = 0.88  # drag coefficient
        A = 0.5  # frontal area (m^2)
        rho = 1.225  # air density (kg/m^3)
        bike_mass = 7  # mass of bike

        # Get values from shared_data with defaults
        power = shared_data.get("power", 0) or 0
        weight = (shared_data.get("weight", 70) or 70) + bike_mass
        gradient = shared_data.get("gradient", 0) or 0  # in degrees
        v = shared_data.get("v", 0) or 0  # current velocity (m/s)

        # Total mass of the system
        total_mass = weight

        # Calculate resistive forces
        f_rolling = C_r * weight * g  # rolling resistance force
        f_drag = 0.5 * C_d * A * rho * v ** 2  # air drag force
        f_grad = weight * g * math.sin(math.radians(gradient))  # gradient force

        # Total resistive force
        f_total = f_rolling + f_drag + f_grad

        # Driving force from power (avoid division by zero for v)
        if v > 0:
            f_drive = power / max(v, 0.1)
        else:
            f_drive = power / 0.1  # small initial velocity to avoid division by zero

        # Net force and acceleration
        f_net = f_drive - f_total
        acceleration = f_net / total_mass  # a = F / m
        max_acceleration = 5.0  # Maximum realistic acceleration (m/s²)
        acceleration = max(-max_acceleration, min(acceleration, max_acceleration))

        # Update velocity iteratively with inertia
        v = max(0, v + acceleration * delta_t)  # velocity cannot be negative

        # Convert velocity to km/h for display purposes
        shared_data["velocity"] = v * 3.6  # in km/h
        shared_data["v"] = v  # Store current velocity in m/s for future calculations

        # Debug data
        debug_data["v"] = v  # in m/s
        debug_data["velocity"] = shared_data["velocity"]  # in km/h
        debug_data["f_rolling"] = f_rolling
        debug_data["f_drag"] = f_drag
        debug_data["f_grad"] = f_grad
        debug_data["f_total"] = f_total
        debug_data["f_drive"] = f_drive
        debug_data["f_net"] = f_net
        debug_data["acceleration"] = acceleration

        return v

    def calculate_wkg():

        power = shared_data.get("power", 0) or 0
        weight = shared_data.get("weight", 70) or 70

        shared_data["wkg"] = power / weight if weight > 0 else 0

    # Execute subfunctions
    calculate_elapsed_time()
    calculate_virtual_speed()
    calculate_wkg()

    # Return updated values for elapsed_start_time and is_moving
    return elapsed_start_time, is_moving







# Print the relevant data
def print_data(shared_data, debug_data, exclude=None, debug=False):
    if exclude is None:
        exclude = []

    # Combine shared_data and debug_data if debug is True
    data_to_print = shared_data.copy()
    if debug:
        data_to_print.update(debug_data)

    output = []
    for key, value in data_to_print.items():
        if key not in exclude and value is not None:
            if isinstance(value, (int, float)):
                output.append(f"{key}: {value:.2f}")
            else:
                output.append(f"{key}: {value}")

    # Print all data inline
    print("\r" + " | ".join(output), end="", flush=True)


# This records the maximum values of each stat, as well as their averages.
def save_max(shared_data, debug_data, file_name="max_values.json"):

    # Clear the file by opening it in write mode and immediately closing it
    open(file_name, "w").close()

    # Initialize max, sums, and counts
    max_values = {}
    avg_sums = {}
    avg_counts = {}

    # Combine shared_data and debug_data
    combined_data = {**shared_data.copy(), **debug_data.copy()}

    # Update max sums and counts
    for key, value in combined_data.items():
        if isinstance(value, (int, float)):

            # Update max values
            max_values[key] = max(max_values.get(key, float('-inf')), value)

            # Update sums and counts for averages
            avg_sums[key] = avg_sums.get(key, 0) + value
            avg_counts[key] = avg_counts.get(key, 0) + 1

    # Calc average values
    avg_values = {key: avg_sums[key] / avg_counts[key] for key in avg_sums}

    # Save the updated data to the JSON file
    with open(file_name, "w") as json_file:
        json.dump(
            {
                "max_values": max_values,
                "avg_values": avg_values,
                "avg_sums": avg_sums,  # Save sums and counts for persistent averages
                "avg_counts": avg_counts,
            },
            json_file,
            indent=4,
        )










'''
Main Loop
'''

async def main():
    # Initialise shared_data before creating tasks
    shared_data, settings, debug_data = init_shared_data(user_profile)

    # Grab some variables from the settings
    trainer_address = settings["trainer_address"]
    trainer_name = settings["trainer_name"]
    hrm_address = settings["hrm_address"]
    hrm_name = settings["hrm_name"]

    # Connect devices
    devices = {
        "trainer": (trainer_address, trainer_name),
        "hrm": (hrm_address, hrm_name),
    }
    connected_clients = await device_connection(devices)

    if connected_clients:
        trainer_client = connected_clients.get("trainer")
        hrm_client = connected_clients.get("hrm")

        if trainer_client:
            # Initialize FTMS
            shared_data, debug_data, trainer_ftms, hrm_ftms = await init_ftms(shared_data, debug_data, trainer_client, hrm_client)

            # Start with the base resistance
            current_resistance = settings.get("base_resistance", 20)

            elapsed_start_time = None
            is_moving = False
            session_start_time = time.time()


            try:
                while True:
                    # RESISTANCE LOGIC GOES HERE. SLOPES ETC
                    desired_resistance = 20

                    # Update resistance only if it has changed
                    current_resistance = await set_resistance(
                        trainer_ftms, desired_resistance, current_resistance, shared_data, retries=10, debug=debug
                    )

                    # Update derived information and get updated elapsed_start_time and is_moving
                    elapsed_start_time, is_moving = derived_information(shared_data, debug_data, elapsed_start_time, is_moving,
                                                                        session_start_time)

                    # Print the data to the console
                    print_data(shared_data, debug_data, "raw_elapsed_time", debug=True)
                    save_max(shared_data, debug_data)

                    await asyncio.sleep(0.1)  # Adjust as needed for real-time updates


            except KeyboardInterrupt:
                print("\nExiting notification loop.")
            finally:
                print("\nDisconnecting devices...")
                await trainer_client.disconnect()
                if hrm_client:
                    await hrm_client.disconnect()
                print("Devices disconnected.")
        else:
            print("Error: Trainer client not connected. Exiting.")
    else:
        print("Error: Could not connect to any devices. Exiting.")





# Run the main loop
asyncio.run(main())