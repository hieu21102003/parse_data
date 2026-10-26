# This is a sample Python script.
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from parsers.std_code_parser import parse_standard_code



# Press Ctrl+F5 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press F9 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print_hi('PyCharm')

    print(sys.path)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
