Electricity Billing System – SQL Integration
This project integrates SQL functions into an electricity billing system's web application. It enables bill retrieval, payment processing, and adjustments using stored procedures and SQL queries. The application is deployed on Oracle Cloud Infrastructure (OCI).

Features
SQL Function Integration: Calls stored procedures for billing operations.
Bill Retrieval & Payments: Fetches bills and processes payments securely.
FastAPI Backend: Handles API requests for the billing system.
Oracle Cloud Deployment: Uses OCI with Nginx and virtual machines.
Technologies Used
FastAPI, Uvicorn
Oracle Database (SQL, Stored Procedures)
Nginx, OCI (Oracle Cloud Infrastructure)
API Endpoints
The following endpoints are available in the Electricity Billing System API:

Method	Endpoint	Description
GET	/bills/{customer_id}	Retrieve customer bill
POST	/pay/{customer_id}	Process payment
PUT	/adjust/{bill_id}	Adjust bill amount
