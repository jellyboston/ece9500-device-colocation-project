# ece9500-device-colocation-project
Course project for ECE 9500 taught by Professor Tara Boroushaki FA 2026. Project members: Jake Boston ('27), Cindy Mo ('27), Dixon Miller ('27), William Flannigan ('27)

## Connecting to the Raspberry Pi 

To ssh: `xrpi4@10.66.56.138`  
When asked for password: `wvkbd`


## Setting up ESP32
Install and setup Platformio following the [tutorial]https://docs.platformio.org/en/stable/integration/ide/vscode.html. Then open a project using the WiSniff folder. It may take ages to setup. This is normal. Just let it run it's course. Afterwards, all should be setup.  

The important files to pay attention to are as follows:
```text
Project Root
├── include/              # Global application header files (.h)
├── lib/                  # Local isolated custom libraries
├── managed_components/   # Automatically managed ESP-IDF components and trees
├── src/                  # Main execution source directory
│   └──  main.cpp          # Main application code (Sniffer setup & execution loops)
├── test/                 # System automation and framework test validation runs
└── platformio.ini        # Project configuration profile (Boards, flags, and dependencies)
```
