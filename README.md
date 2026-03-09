# Parking-management-system

A full-stack parking management web application built with **Python Flask** and **Oracle Database (PL/SQL)**, featuring role-based authentication, real-time dashboards for Admin and Agent, and full CRUD operations.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask · REST API |
| Database | Oracle DB · SQL · PL/SQL |
| ORM / Driver | python-oracledb |
| Frontend | HTML · CSS · JavaScript |
| Auth | Session-based · Role-based (Admin / Agent) |

---

## Features

### Authentication & Roles
- Secure login with Oracle DB credentials
- Two roles: **ADMIN** and **AGENT**
- Route protection with custom decorators (`@admin_required`, `@agent_required`)

### Admin Dashboard
- Full client management (Add / Update / Delete)
- Parking space management (type, availability)
- Tariff management via PL/SQL stored procedure
- Real-time parking statistics (occupancy rate, revenue, subscribers)

### Agent Dashboard
- Register vehicle entry → auto-assigns parking spot + generates ticket
- Validate vehicle exit → auto-calculates payment
- View active reservations and tickets
- Subscribe new clients

### Database (Oracle PL/SQL)
- Normalized relational schema (Clients, Places, Reservations, Tickets, Payments, Subscriptions, Tariffs)
- Stored procedures: `ajouter_entree`, `valider_sortie`, `s_abonner`, `mettre_a_jour_tarifs`
- Functions: `total_clients`, `total_abonnes`, `taux_d_occup_places`, `revenu_d_jour`
- Triggers for automatic place availability update
- Constraints & transactions for data integrity

---

## Project Structure

```
parking-management-system/
│
├── app.py                  # Flask application & REST API routes
├── requirements.txt        # Python dependencies
│
├── templates/
│   ├── home.html           # Login page
│   ├── ADMINN.html         # Admin dashboard
│   └── AGENTT.html         # Agent dashboard
│
└── parking.sql             # Full Oracle DB schema + PL/SQL code
```

---

### Prerequisites
- Python 3.8+
- Oracle Database XE (or higher)
- Oracle Instant Client

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/khadija570/parking-management-system
cd parking-management-system

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up the Oracle database
# Run parking.sql in SQL Developer or SQLPlus

# 4. Configure DB credentials in app.py
DB_CONFIG = {
    'user': 'YOUR_USER',
    'password': 'YOUR_PASSWORD',
    'dsn': 'localhost:1521/XEPDB1'
}

# 5. Run the app
python app.py
```

### Access the app
```
http://localhost:5000
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/login` | Authenticate user |
| GET | `/logout` | Logout |
| GET | `/clients` | List all clients |
| POST | `/client/add` | Add a client |
| PUT | `/client/update/<id>` | Update a client |
| DELETE | `/client/delete/<id>` | Delete a client |
| GET | `/places` | List all parking spots |
| GET | `/places/disponibles` | Available spots only |
| POST | `/entree` | Register vehicle entry |
| POST | `/sortie` | Validate vehicle exit |
| GET | `/reservations` | List reservations |
| GET | `/abonnements` | List subscriptions |
| POST | `/abonner` | Create subscription |
| GET | `/paiements` | List payments |
| GET | `/statistiques` | Parking statistics |
| PUT | `/tarif/update` | Update tariffs (Admin) |

---

## Author

**Khadija El Gourain**  
Engineering Student — Data Science, Big Data & AI @ ENSA Agadir  
[Portfolio](https://khadija570.github.io) · [LinkedIn](https://www.linkedin.com/in/khadija-el-gourain) · [GitHub](https://github.com/khadija570)
