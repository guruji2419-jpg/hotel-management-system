"""
hotel_manager.py
----------------
Core logic and data structure for the Hotel Management System.
Features simple, artistic terminal output with ASCII frames & emojis,
plus JSON persistent storage so bookings are saved to disk.
"""

import json
import os

DATA_FILE = "hotel_data.json"

# Default initial room data structure
INITIAL_ROOMS = {
    "101": {"type": "Standard", "price": 50,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "102": {"type": "Standard", "price": 50,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "103": {"type": "Deluxe",   "price": 80,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "201": {"type": "Deluxe",   "price": 80,  "status": "Available", "guest": None, "nights": 0, "services": 0},
    "202": {"type": "Suite",    "price": 150, "status": "Available", "guest": None, "nights": 0, "services": 0},
}


def load_rooms():
    """Loads room data from hotel_data.json if it exists, else returns initial default data."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            print("  ⚠️ Could not read saved data file. Using default rooms.")
    return INITIAL_ROOMS.copy()


def save_rooms(rooms):
    """Saves room data to hotel_data.json."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(rooms, f, indent=4)
    except Exception as e:
        print(f"  ❌ Error saving data: {e}")


def print_banner(title):
    """Prints a styled artistic banner header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  ✨ {title.upper()} ✨".center(width))
    print("═" * width)


def display_rooms(rooms):
    """Displays an artistic table of all hotel rooms."""
    print_banner("Hotel Room Status")
    
    print(f"  {'ROOM':<8} {'TYPE':<12} {'PRICE/NIGHT':<15} {'STATUS':<15} {'GUEST'}")
    print("  " + "─" * 56)
    
    for room_num, info in rooms.items():
        if info["status"] == "Available":
            status_badge = "🟢 Available"
        else:
            status_badge = "🔴 Occupied"
            
        guest_name = info.get("guest") if info.get("guest") else "-"
        print(f"  {room_num:<8} {info['type']:<12} ${info['price']:<14} {status_badge:<15} {guest_name}")
        
    print("  " + "─" * 56)


def check_in_guest(rooms):
    """Handles checking a new guest into an available room."""
    print_banner("Guest Check-In")
    
    available_rooms = [r for r, info in rooms.items() if info["status"] == "Available"]
    
    if not available_rooms:
        print("  ⚠️  Sorry! All rooms are currently occupied.")
        return

    print(f"  Available Rooms: {', '.join(available_rooms)}")
    room_num = input("  Enter Room Number to book: ").strip()
    
    if room_num not in rooms:
        print("  ❌ Invalid Room Number! Please try again.")
        return
        
    if rooms[room_num]["status"] != "Available":
        print(f"  ❌ Room {room_num} is already OCCUPIED! Please choose an available room.")
        return

    guest_name = input("  Enter Guest Name: ").strip()
    if not guest_name:
        print("  ❌ Guest name cannot be empty!")
        return

    try:
        nights = int(input("  Enter Number of Nights: ").strip())
        if nights <= 0:
            print("  ❌ Nights must be at least 1!")
            return
    except ValueError:
        print("  ❌ Please enter a valid number for nights!")
        return

    # Update Room Data
    rooms[room_num]["status"] = "Occupied"
    rooms[room_num]["guest"] = guest_name
    rooms[room_num]["nights"] = nights
    rooms[room_num]["services"] = 0

    save_rooms(rooms)

    total_cost = rooms[room_num]["price"] * nights

    # Artistic Check-In Ticket
    print("\n" + "┌" + "─" * 44 + "┐")
    print("│         🎉 CHECK-IN CONFIRMED 🎉           │")
    print("├" + "─" * 44 + "┤")
    print(f"│  Guest Name   : {guest_name:<26} │")
    print(f"│  Room Number  : {room_num:<26} │")
    print(f"│  Room Type    : {rooms[room_num]['type']:<26} │")
    print(f"│  Stay Length  : {nights:<2} night(s){' ':<15} │")
    print(f"│  Est. Total   : ${total_cost:<25} │")
    print("└" + "─" * 44 + "┘")
    print("  💾 Saved to database successfully!")


def check_out_guest(rooms):
    """
    PHASE 4: Guest Check-Out & Itemized Invoice Calculation
    Search by Room Number or Guest Name, add room service charges, and calculate final bill.
    """
    print_banner("Guest Check-Out & Billing")
    
    occupied_rooms = {r: info for r, info in rooms.items() if info["status"] == "Occupied"}
    
    if not occupied_rooms:
        print("  ℹ️  No rooms are currently occupied.")
        return

    print("  Occupied Rooms:")
    for r, info in occupied_rooms.items():
        print(f"    - Room {r}: {info['guest']} ({info['nights']} nights)")
    print("  " + "─" * 40)
    
    query = input("\n  Enter Room Number or Guest Name: ").strip()

    # Search by room number or guest name (case-insensitive)
    target_room = None
    if query in rooms and rooms[query]["status"] == "Occupied":
        target_room = query
    else:
        for r, info in occupied_rooms.items():
            if query.lower() in info["guest"].lower():
                target_room = r
                break

    if not target_room:
        print("  ❌ No matching occupied room found!")
        return

    info = rooms[target_room]
    guest_name = info["guest"]
    nights = info["nights"]
    price = info["price"]
    room_charge = price * nights

    # Optional Add-on Services prompt
    add_services = input("  Add Room Service / Mini-Bar charges ($)? [Press Enter for $0]: ").strip()
    services_charge = 0.0
    if add_services:
        try:
            services_charge = float(add_services)
            if services_charge < 0:
                services_charge = 0.0
        except ValueError:
            print("  ⚠️ Invalid charge amount. Setting service charge to $0.")
            services_charge = 0.0

    total_bill = room_charge + services_charge

    # Artistic Bill Invoice
    print("\n" + "┌" + "─" * 46 + "┐")
    print("│             🧾 HOTEL INVOICE 🧾              │")
    print("├" + "─" * 46 + "┤")
    print(f"│  Guest Name    : {guest_name:<27} │")
    print(f"│  Room Number   : {target_room:<27} │")
    print(f"│  Room Type     : {info['type']:<27} │")
    print(f"│  Rate / Night  : ${price:<26} │")
    print(f"│  Nights Stayed : {nights:<27} │")
    print("├" + "─" * 46 + "┤")
    print(f"│  Room Total    : ${room_charge:<26.2f} │")
    print(f"│  Service Addons: ${services_charge:<26.2f} │")
    print("├" + "─" * 46 + "┤")
    print(f"│  FINAL TOTAL   : ${total_bill:<26.2f} │")
    print("└" + "─" * 46 + "┘")

    # Reset Room Data & Save
    rooms[target_room]["status"] = "Available"
    rooms[target_room]["guest"] = None
    rooms[target_room]["nights"] = 0
    rooms[target_room]["services"] = 0
    save_rooms(rooms)
    
    print(f"\n  ✅ Room {target_room} is now checked out and available!")
    print("  💾 Database updated successfully!")


def display_dashboard(rooms):
    """Displays hotel analytics and dashboard summary."""
    print_banner("Hotel Dashboard")
    
    total = len(rooms)
    occupied = sum(1 for r in rooms.values() if r["status"] == "Occupied")
    available = total - occupied
    occupancy_rate = (occupied / total) * 100
    
    pending_revenue = sum(r["price"] * r["nights"] for r in rooms.values() if r["status"] == "Occupied")

    print(f"  🏨 Total Rooms      : {total}")
    print(f"  🟢 Available Rooms  : {available}")
    print(f"  🔴 Occupied Rooms   : {occupied}")
    print(f"  📊 Occupancy Rate   : {occupancy_rate:.1f}%")
    print(f"  💰 Current Revenue  : ${pending_revenue:.2f}")
    print("  " + "─" * 30)
