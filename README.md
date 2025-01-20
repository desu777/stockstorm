# 📊 Microservice Bot for Automated Trading

This project implements a Django-based **microservice** designed for managing and automating trading bots. The system integrates with the **XTB WebSocket API** to provide real-time market updates and execute trades based on predefined levels. The project is developed in compliance with the **MVC (Model-View-Controller)** pattern.

---
![start](https://github.com/user-attachments/assets/5f0e52f0-6ba3-4dfb-92a4-b16c3b54ca37)




## 🚀 Features

### 🎛️ **Core Functionalities**
- **Bot Management**:
  - Create, view, edit, and delete trading bots.
  - Define bot parameters like trading instrument, price levels, and target profit percentage.
![start2](https://github.com/user-attachments/assets/410bce83-6bf2-4e29-bb34-7783e242c1b3)
![start3](https://github.com/user-attachments/assets/2a5c5a00-d8b5-4d15-bd89-5d772a4a0383)
![strt3](https://github.com/user-attachments/assets/8fb8c508-b059-454b-9f4c-eb9fdfb2db4e)


- **Real-Time Trading**:
  - Integrates with XTB WebSocket API for real-time price updates.
  - Automatically triggers buy/sell orders based on predefined logic.
- **Dynamic Capital Allocation**:
  - Supports reinvestment and profit tracking for bots.
  - Monitors multiple price levels and dynamically adjusts capital.

### 🔧 **API Endpoints**
| Method | Endpoint                        | Description                      |
|--------|---------------------------------|----------------------------------|
| POST   | `/create_bot/`                  | Create a new bot                |
| GET    | `/get_bot_details/<bot_id>/`    | Retrieve bot details            |
| POST   | `/remove_bot/<bot_id>/`         | Remove a bot                    |
| POST   | `/sync_session_id/`             | Sync session ID for a bot       |
| POST   | `/start_stream/`                | Start WebSocket stream          |
| POST   | `/register-token/`              | Register user authentication token |

---

## 🛠️ **System Requirements**
- **Python 3.10+**
- **Django 4.2+**
- **SQLite/MySQL** for database management
- **pip** for dependency management

---

## 📝 **Installation and Setup**

### 1. Clone the Repository
```bash
git clone https://github.com/desu777/stockstorm
cd microservice-bot
