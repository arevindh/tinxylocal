import requests
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from zeroconf._exceptions import BadTypeInNameException
import json


class TinxyServiceListener(ServiceListener):
    def __init__(self):
        self.tinxy_devices = []  # To store Tinxy devices from the API

    def add_service(self, zeroconf, service_type, name):
        if name.startswith("tinxy"):
            try:
                info = zeroconf.get_service_info(service_type, name)
                if info:
                    device_id_suffix = name[5:10]
                    matched_device = self.find_matching_device(device_id_suffix)
                    if matched_device:
                        ip_address = ".".join(map(str, info.addresses[0]))
                        print(f"Service Name: {name}")
                        print(f"Address: {ip_address}")
                        print(
                            f"Supports local control: {'Yes' if self.check_local_api(ip_address) else 'No'}"
                        )
                        print(f"Port: {info.port}")
                        print(f"Device Name : {matched_device.get('name')}")
                        print("--------------------------------------------------")
                    else:
                        print(f"No matching API device found for service: {name}")
            except BadTypeInNameException:
                print(f"Skipped service with invalid name or type: {name}")

    def remove_service(self, zeroconf, service_type, name):
        if name.startswith("tinxy"):
            print(f"Service removed: {name}")

    def get_tinxy_devices(self):
        url = "https://ha-backend.tinxy.in/v2/devices"
        token = input("Please enter your Bearer token: ")
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            try:
                self.tinxy_devices = response.json()
            except json.JSONDecodeError:
                print("Failed to parse JSON response.")
        else:
            print(f"Failed to fetch devices. Status code: {response.status_code}")

    def find_matching_device(self, device_id_suffix):
        for device in self.tinxy_devices:
            if device["_id"][-5:] == device_id_suffix:
                return device
        return None

    def check_local_api(self, ip_address):
        try:
            response = requests.get(f"http://{ip_address}/info", timeout=1)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name.startswith("tinxy"):
            print(f"Service {name} updated")


zeroconf = Zeroconf()
listener = TinxyServiceListener()

try:
    listener.get_tinxy_devices()
    ServiceBrowser(zeroconf, "_http._tcp.local.", listener)
    input("Press Enter to exit...\n")
finally:
    zeroconf.close()
