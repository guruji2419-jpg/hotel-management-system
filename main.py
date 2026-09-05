"""
main.py
-------
Interactive CLI Main Menu for the Hotel Management System.
Connects hotel_manager functions into a user-friendly terminal interface.
"""

import sys
from hotel_manager import (
    load_rooms,
    display_rooms,
    check_in_guest,
    check_out_guest,
    display_dashboard,
    display_maintenance_menu
)


def print_main_menu():
    """Prints an artistic main menu frame."""
    print("\n" + "╔" + "═" * 44 + "╗")
    print("║      🏨 GRAND HORIZON HOTEL SYSTEM 🏨       ║")
    print("╠" + "═" * 44 + "╣")
    print("║  1. 📋 View All Rooms                      ║")
    print("║  2. 🛎️  Check-In Guest                     ║")
    print("║  3. 🧾 Check-Out Guest & Bill              ║")
    print("║  4. 📊 Hotel Dashboard & Stats             ║")
    print("║  5. 🔧 Room Maintenance Management         ║")
    print("║  6. 🚪 Exit                                ║")
    print("╚" + "═" * 44 + "╝")


def main():
    # Load rooms from disk (or initialize defaults)
    rooms = load_rooms()
    
    print("\n✨ Welcome to your Hotel Management System CLI! ✨")
    
    while True:
        try:
            print_main_menu()
            choice = input("  Select an option (1-6): ").strip()
            
            if choice == "1":
                display_rooms(rooms)
            elif choice == "2":
                check_in_guest(rooms)
            elif choice == "3":
                check_out_guest(rooms)
            elif choice == "4":
                display_dashboard(rooms)
            elif choice == "5":
                display_maintenance_menu()
            elif choice == "6":
                print("\n  👋 Thank you for using Grand Horizon Hotel System. Goodbye!\n")
                break
            else:
                print("\n  ❌ Invalid choice! Please enter a number between 1 and 6.")
                
        except (KeyboardInterrupt, EOFError):
            print("\n\n  👋 Program interrupted. Goodbye!")
            sys.exit(0)


if __name__ == "__main__":
    main()
