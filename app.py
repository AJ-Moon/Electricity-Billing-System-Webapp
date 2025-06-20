from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import time
import datetime
from datetime import date
from datetime import datetime
import os
import logging
import oracledb
import uvicorn
# Port = 22
# IP = 193.123.92.235

d = os.environ.get("ORACLE_HOME")               # Defined by the file `oic_setup.sh`
oracledb.init_oracle_client(lib_dir=d)          # Thick mode

# These environment variables come from `env.sh` file.
user_name = os.environ.get("DB_USERNAME")
user_pswd = os.environ.get("DB_PASSWORD")
db_alias  = os.environ.get("DB_ALIAS")

# make sure to setup connection with the DATABASE SERVER FIRST. refer to python-oracledb documentation for more details on how to connect, and run sql queries and PL/SQL procedures.

app = FastAPI()

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)

origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
) 
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# -----------------------------
# API Endpoints
# -----------------------------

# ---------- GET methods for the pages ----------
@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Bill payment page
@app.get("/bill-payment", response_class=HTMLResponse)
async def get_bill_payment(request: Request):
    return templates.TemplateResponse("bill_payment.html", {"request": request})

# Bill generation page
@app.get("/bill-retrieval", response_class=HTMLResponse)
async def get_bill_retrieval(request: Request):
    return templates.TemplateResponse("bill_retrieval.html", {"request": request})

# Adjustments page
@app.get("/bill-adjustments", response_class=HTMLResponse)
async def get_bill_adjustment(request: Request):
    return templates.TemplateResponse("bill_adjustment.html", {"request": request})


# ---------- POST methods for the pages ----------
@app.post("/bill-payment", response_class=HTMLResponse)
async def post_bill_payment(request: Request, bill_id: int = Form(...), amount: float = Form(...), payment_method_id: int = Form(...)):
    # Handle billing payment here
    try:
        connection = oracledb.connect(user=user_name, password=user_pswd, dsn=db_alias)
        cursor = connection.cursor()
        logger.info("Database connection established successfully.")

        # Query to get the bill details
        cursor.execute("""
            SELECT  TotalAmount_BeforeDueDate, TotalAmount_AfterDueDate, DueDate 
            FROM Bill 
            WHERE BillID = :bill_id
        """, bill_id=bill_id)
        bill_row = cursor.fetchone()
        if not bill_row:
            return templates.TemplateResponse(
                  "error.html",
        {"request": request, "message": "Bill ID doesn't exist"}
            )
            
        total_amount_before_due_date, total_amount_after_due_date, due_date = bill_row
        today = date.today()
        if isinstance(due_date, datetime):
            due_date = due_date.date()
        bill_amount = total_amount_after_due_date if today > due_date else total_amount_before_due_date
        outstanding_amount = bill_amount - amount
        payment_status = 'Fully Paid' if outstanding_amount <= 0 else 'Partially Paid'
        result = cursor.callfunc(
            "fun_process_Payment",
            int, 
            [bill_id, today, payment_method_id, amount]
        )

        if result == 1: 
            logger.info(f"Payment processed successfully for Bill ID {bill_id}.")
            connection.commit()


        cursor.execute("""
            SELECT PaymentMethodDescription 
            FROM PaymentMethods 
            WHERE PaymentMethodID = :payment_method_id
        """, payment_method_id=payment_method_id)
        payment_method_desc = cursor.fetchone()
        payment_method_description = payment_method_desc[0]

    except oracledb.DatabaseError as e:
        connection.rollback()
        return f"Database error: {str(e)}", 500

    finally:
        cursor.close()
        connection.close()
        
    # Retrive the details required in the dictionary, by querying your database, or running appropriate functions
    payment_details = {
        "bill_id": bill_id,
        "amount": amount,
        "payment_method_id": payment_method_id,
        "payment_method_description": payment_method_description,
        "payment_date": today,
        "payment_status": payment_status,
        "outstanding_amount": outstanding_amount,
    }

    return templates.TemplateResponse("payment_receipt.html", {"request": request, "payment_details": payment_details})


@app.post("/bill-retrieval", response_class=HTMLResponse)
async def post_bill_retrieval(request: Request, customer_id: str = Form(...), connection_id: str = Form(...), month: str = Form(...), year: str = Form(...)):
    # Here, you would generate the bill
    try:
        connection = oracledb.connect(user=user_name, password=user_pswd, dsn=db_alias)
        cursor = connection.cursor()
        logger.info("Database connection established successfully.")
        
        # Query for customer and connection details
        query_customer = """
        SELECT 
            c.CustomerID, 
            c.FirstName || ' ' || c.LastName AS CustomerName, 
            c.Address, 
            c.PhoneNumber, 
            c.Email, 
            ct.Description AS ConnectionType, 
            di.DivisionName, 
            di.SubDivName, 
            conn.InstallationDate, 
            conn.MeterType 
        FROM Customers c
        JOIN Connections conn ON c.CustomerID = conn.CustomerID
        JOIN ConnectionTypes ct ON conn.ConnectionTypeCode = ct.ConnectionTypeCode
        JOIN DivInfo di ON conn.DivisionID = di.DivisionID AND conn.SubDivID = di.SubDivID
        WHERE c.CustomerId = :customer_id 
        AND conn.CONNECTIONID = :connection_id
        """ 
        print(f"Executing query: {query_customer}")
        cursor.execute(query_customer, customer_id=customer_id, connection_id=connection_id)
        customer_row = cursor.fetchone()
        
        if not customer_row:
            return templates.TemplateResponse(
                "error.html", 
                {"request": request, "message": "Customer or Connection not found."}
            )
        
        (
             CustomerID, CustomerName, Address, PhoneNumber, Email,
            ConnectionType, DivisionName, SubDivName, InstallationDate, meter_type
        ) = customer_row
        
        # Query for bill details
        query_bill = """
        SELECT 
            b.BillIssueDate, 
            b.Net_PeakUnits, 
            b.Net_OffPeakUnits, 
            b.TotalAmount_BeforeDueDate AS BillAmount, 
            b.DueDate, 
            b.TotalAmount_AfterDueDate AS AmountAfterDueDate, 
            b.BillingMonth, 
            b.BillingYear, 
            b.Arrears,
            fun_compute_FixedFee(conn.ConnectionID, b.BillingMonth, b.BillingYear, b.BillIssueDate) AS FixedFee,
            b.TaxAmount 
            FROM Bill b
            JOIN connections conn ON b.connectionid = conn.connectionid
            JOIN customers c ON conn.customerid = c.customerid
            WHERE b.BillingMonth = :month
            AND b.BillingYear = :year
            AND b.ConnectionId = ( SELECT ConnectionID
            FROM Connections conn
            WHERE conn.CustomerID =: customer_id
            AND conn.ConnectionID =: connection_id
            )
          
        """
        print(f"Executing query: {query_bill}")
        cursor.execute(query_bill, customer_id=customer_id, connection_id=connection_id, month=month, year=year)
        bill_row = cursor.fetchone()
        
        if not bill_row:
            return templates.TemplateResponse(
                "error.html", 
                {"request": request, "message": "Bill not found for the specified month and year."}
            )
        
        (
            BillIssueDate, Net_PeakUnits, Net_OffPeakUnits, BillAmount, DueDate, AmountAfterDueDate, 
            BillingMonth, BillingYear, Arrears, FixedFee, TaxAmount 
        ) = bill_row


        tariffs_query = """
        SELECT 
            t.TarrifDescription,
            b.Import_OffPeakUnits,
            b.Import_PeakUnits,
            t.RatePerUnit,
            CASE 
                WHEN t.TariffType = 1 THEN 
                    fun_compute_PeakAmount(conn.ConnectionID, b.BillingMonth, b.BillingYear, b.BillIssueDate)
                WHEN t.TariffType = 2 THEN 
                    fun_compute_OffPeakAmount(conn.ConnectionID, b.BillingMonth, b.BillingYear, b.BillIssueDate)
            END AS ComputedAmount
        FROM 
            Tariff t
        JOIN 
            ConnectionTypes ct ON t.ConnectionTypeCode = ct.ConnectionTypeCode
        JOIN 
            Connections conn ON ct.ConnectionTypeCode = conn.ConnectionTypeCode
        JOIN 
            Bill b ON conn.ConnectionID = b.ConnectionID
        WHERE
            b.BillingMonth = :month
            AND b.BillingYear = :year    
            AND conn.CustomerID = :customer_id
            AND conn.ConnectionID = :connection_id
        ORDER BY 
            t.TariffType ASC
        """

        print(f"Executing query: {tariffs_query}")
        cursor.execute(tariffs_query, customer_id=customer_id, connection_id=connection_id, month=int(month), year=int(year))
        tariffs = cursor.fetchall()


        taxes_query = """
        SELECT tr.TaxType, tr.Rate 
        FROM TaxRates tr
        JOIN 
            ConnectionTypes ct ON tr.ConnectionTypeCode = ct.ConnectionTypeCode
        JOIN 
            Connections conn ON ct.ConnectionTypeCode = conn.ConnectionTypeCode
        JOIN 
            Bill b ON conn.ConnectionID = b.ConnectionID
        WHERE
            b.BillingMonth = :month
        AND b.BillingYear = :year    
        AND conn.CustomerID =: customer_id
        AND conn.ConnectionID =: connection_id
        """
        print(f"Executing query: {taxes_query}")
        cursor.execute(taxes_query, customer_id=customer_id, connection_id=connection_id, month=int(month), year=int(year))
        taxes = cursor.fetchall()

        # Querying applied subsidies
        subsidies_query = """
        SELECT s.SubsidyDescription, s.ProviderID, s.RatePerUnit 
        FROM Subsidy s
        JOIN 
            ConnectionTypes ct ON s.ConnectionTypeCode = ct.ConnectionTypeCode
        JOIN 
            Connections conn ON ct.ConnectionTypeCode = conn.ConnectionTypeCode
        JOIN 
            Bill b ON conn.ConnectionID = b.ConnectionID
        WHERE
            b.BillingMonth = :month
        AND b.BillingYear = :year    
        AND conn.CustomerID =: customer_id
        AND conn.ConnectionID =: connection_id
        """
        print(f"Executing query: {subsidies_query}")
        cursor.execute(subsidies_query, customer_id=customer_id, connection_id=connection_id, month=int(month), year=int(year))
        subsidies = cursor.fetchall()

        # Querying fixed fees
        fixed_fees_query = """
        SELECT fc.FixedChargeType, fc.FixedFee 
        FROM FixedCharges fc
       JOIN 
            ConnectionTypes ct ON fc.ConnectionTypeCode = ct.ConnectionTypeCode
        JOIN 
            Connections conn ON ct.ConnectionTypeCode = conn.ConnectionTypeCode
        JOIN 
            Bill b ON conn.ConnectionID = b.ConnectionID
        WHERE
            b.BillingMonth = :month
        AND b.BillingYear = :year    
        AND conn.CustomerID =: customer_id
        AND conn.ConnectionID =: connection_id
        """
        print(f"Executing query: {fixed_fees_query}")
        cursor.execute(fixed_fees_query, customer_id=customer_id, connection_id=connection_id, month=int(month), year=int(year))
        fixed_fees = cursor.fetchall()

        # Querying previous bills
        previous_bills_query = """
        SELECT *
        FROM (SELECT b.BillingMonth, b.BillingYear, b.TotalAmount_BeforeDueDate , b.DueDate, pd.PaymentStatus
        FROM Bill b
        JOIN 
            Connections conn ON b.ConnectionID = conn.ConnectionID
        JOIN
            PaymentDetails pd ON b.BillID = pd.BillID    
        WHERE  
        conn.CustomerID =: customer_id
        AND conn.ConnectionID =: connection_id
        ORDER BY b.BILLissuedate DESC)
        WHERE ROWNUM <= 10
        """
        print(f"Executing query: {previous_bills_query}")
        cursor.execute(previous_bills_query, customer_id=customer_id, connection_id=connection_id)
        previous_bills = cursor.fetchall()

    except oracledb.DatabaseError as e:
        logger.error(f"Database error: {str(e)}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "message": "An error occurred while retrieving data."}
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "message": "An unexpected error occurred. Please try again later."}
        )
    finally:
        try:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
            logger.info("Database connection closed.")
        except Exception as close_error:
            logger.error(f"Error while closing the connection: {str(close_error)}")

    # Retrive the details required in the dictionary, by querying your database, or running appropriate functions
    # the values in this dict are hardcoded for now. you will be populating it dynamically.
    bill_details = {
        "customer_id": customer_id,
        "connection_id": connection_id,
        "customer_name": CustomerName,
        "customer_address": Address,
        "customer_phone": PhoneNumber,
        "customer_email": Email,
        "connection_type": ConnectionType,
        "division": DivisionName,
        "subdivision": SubDivName,
        "installation_date": InstallationDate,
        "meter_type": meter_type,
        "issue_date": BillIssueDate,
        "net_peak_units": Net_PeakUnits,
        "net_off_peak_units": Net_OffPeakUnits,
        "bill_amount": BillAmount,
        "due_date": DueDate,
        "amount_after_due_date": AmountAfterDueDate,
        "month": BillingMonth,
        "year": BillingYear,
        "arrears_amount": Arrears,
        "fixed_fee_amount": FixedFee,
        "tax_amount": TaxAmount,
        # all the applicable tariffs
        "tariffs": [
            {"name": t[0], "units": t[1], "rate": t[3], "amount": t[4]} for t in tariffs],
        # applicable taxes
        "taxes":
        [{"name": t[0], "amount": t[1]} for t in taxes],
        # applicable subsidies
        "subsidies": 
        [{"name": s[0], "provider_name": s[1], "rate_per_unit": s[2]} for s in subsidies],
        # applicable fixed fees
        "fixed_fee": 
           [{"name": f[0], "amount": f[1]} for f in fixed_fees],
        # the last 10 (or lesser) bills of the customer
        "bills_prev":
            [{"month": f"{b[0]}-{b[1]}", "amount": b[2], "due_date": b[3], "status": b[4]} for b in previous_bills],
    }
    
    return templates.TemplateResponse("bill_details.html", {"request": request, "bill_details": bill_details})


# Code for handling adjustments goes here
@app.post("/bill-adjustments", response_class=HTMLResponse)
async def post_bill_adjustments(
    request: Request,
    bill_id: int = Form(...),
    officer_name: str = Form(...),
    officer_designation: str = Form(...),
    original_bill_amount: float = Form(...),
    adjustment_amount: float = Form(...),
    adjustment_reason: str = Form(...),
):
    
    try:
        connection = oracledb.connect(user=user_name, password=user_pswd, dsn=db_alias)
        cursor = connection.cursor()
        logger.info("Database connection established successfully.")

        cursor.execute("""
        SELECT TotalAmount_BeforeDueDate, TotalAmount_AfterDueDate, DueDate 
        FROM Bill 
        WHERE BillID = :bill_id
        """, bill_id=bill_id)
        bill_row = cursor.fetchone()

        if not bill_row:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Invalid Bill ID"}
            )
        cursor.execute("""
        SELECT AdjustmentID
        FROM BillAdjustments
        ORDER BY AdjustmentID DESC
        FETCH FIRST 1 ROWS ONLY
        """)
        adjustment_id_row = cursor.fetchone()

        # If no adjustment exists, initialize adjustment_id
        if adjustment_id_row:
            adjustment_id = int(adjustment_id_row[0]) + 1  # Increment the highest ID
        else:
            adjustment_id = 1  # If no adjustments exist, start from 1

        today = date.today()
        cursor.execute("""
            INSERT INTO BillAdjustments (AdjustmentID, BillID, OfficerName, OfficerDesignation, 
                                        OriginalBillAmount, AdjustmentAmount, 
                                        AdjustmentReason, AdjustmentDate)
            VALUES (:adjustment_id, :bill_id, :officer_name, :officer_designation, 
                    :original_bill_amount, :adjustment_amount, 
                    :adjustment_reason, :adjustment_date)
        """, adjustment_id=adjustment_id, bill_id=bill_id, officer_name=officer_name,
            officer_designation=officer_designation, original_bill_amount=original_bill_amount,
            adjustment_amount=adjustment_amount,
            adjustment_reason=adjustment_reason, adjustment_date=today)
        
        connection.commit()

    except oracledb.DatabaseError as e:
        logger.error(f"Database error: {e}")
        connection.rollback()  # Rollback in case of an error
        return "Database error", 500
    finally:
        cursor.close()
        connection.close()


      # Retrive the details required in the dictionary, by querying your database, or running appropriate functions
    adjustment_details = {
        "adjustment_id": adjustment_id,
        "bill_id": bill_id,
        "officer_name": officer_name,
        "officer_designation": officer_designation,
        "original_bill_amount": original_bill_amount,
        "adjustment_amount": adjustment_amount,
        "adjustment_reason": adjustment_reason,
        "adjustment_date": today
    }

    return templates.TemplateResponse("adjustment_reciept.html", {"request": request, "adjustment_receipt": adjustment_details})
if __name__ == "__main__":
    uvicorn.run(app, host='0.0.0.0', port=8000)
