import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import json
import base64

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('paytrack.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inv_number TEXT,
                    date TEXT,
                    b_name TEXT, b_phone TEXT, b_email TEXT, b_address TEXT,
                    c_name TEXT, c_phone TEXT, c_email TEXT,
                    total REAL, amount_paid REAL, balance REAL,
                    status TEXT,
                    items TEXT
                )''')
    conn.commit()
    conn.close()

def get_next_invoice_number():
    conn = sqlite3.connect('paytrack.db')
    c = conn.cursor()
    c.execute("SELECT inv_number FROM invoices ORDER BY id DESC LIMIT 1")
    last_inv = c.fetchone()
    conn.close()
    
    if last_inv:
        last_num = int(last_inv[0].split('-')[1])
        return f"INV-{(last_num + 1):04d}"
    return "INV-0001"

def save_invoice(data):
    conn = sqlite3.connect('paytrack.db')
    c = conn.cursor()
    c.execute('''INSERT INTO invoices 
                 (inv_number, date, b_name, b_phone, b_email, b_address, 
                  c_name, c_phone, c_email, total, amount_paid, balance, status, items) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (data['inv_number'], data['date'], data['b_name'], data['b_phone'], 
               data['b_email'], data['b_address'], data['c_name'], data['c_phone'], 
               data['c_email'], data['total'], data['amount_paid'], data['balance'], 
               data['status'], json.dumps(data['items'])))
    conn.commit()
    conn.close()

# --- PDF GENERATOR ---
def create_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Header
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(200, 10, txt="INVOICE", ln=True, align='R')
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt=data['b_name'], ln=True, align='L')
    
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 5, txt=f"Email: {data['b_email']} | Phone: {data['b_phone']}", ln=True, align='L')
    if data['b_address']:
        pdf.cell(200, 5, txt=data['b_address'], ln=True, align='L')
        
    pdf.ln(10)
    
    # Invoice Details & Customer Info
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(100, 8, txt="Bill To:", border=0)
    pdf.cell(90, 8, txt=f"Invoice No: {data['inv_number']}", border=0, align='R', ln=True)
    
    pdf.set_font("Arial", size=10)
    pdf.cell(100, 5, txt=data['c_name'], border=0)
    pdf.cell(90, 5, txt=f"Date: {data['date']}", border=0, align='R', ln=True)
    pdf.cell(100, 5, txt=f"Email: {data['c_email']}", border=0, ln=True)
    pdf.cell(100, 5, txt=f"Phone: {data['c_phone']}", border=0, ln=True)
    
    pdf.ln(10)
    
    # Table Header
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(200, 200, 200)
    pdf.cell(80, 8, "Description", 1, 0, 'L', 1)
    pdf.cell(30, 8, "Quantity", 1, 0, 'C', 1)
    pdf.cell(40, 8, "Unit Price (R)", 1, 0, 'R', 1)
    pdf.cell(40, 8, "Total (R)", 1, 1, 'R', 1)
    
    # Table Rows
    pdf.set_font("Arial", size=10)
    for item in data['items']:
        if item['Description'].strip():
            pdf.cell(80, 8, str(item['Description']), 1)
            pdf.cell(30, 8, str(item['Quantity']), 1, 0, 'C')
            pdf.cell(40, 8, f"R {item['Unit Price']:.2f}", 1, 0, 'R')
            pdf.cell(40, 8, f"R {item['Total']:.2f}", 1, 1, 'R')
            
    pdf.ln(5)
    
    # Totals
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(150, 8, "Subtotal:", border=0, align='R')
    pdf.cell(40, 8, f"R {data['total']:.2f}", border=0, align='R', ln=True)
    
    pdf.cell(150, 8, "Amount Paid:", border=0, align='R')
    pdf.cell(40, 8, f"R {data['amount_paid']:.2f}", border=0, align='R', ln=True)
    
    pdf.cell(150, 8, "Outstanding Balance:", border=0, align='R')
    pdf.cell(40, 8, f"R {data['balance']:.2f}", border=0, align='R', ln=True)
    
    # Status
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    status_text = f"Status: {data['status'].upper()}"
    pdf.cell(190, 10, txt=status_text, align='R', ln=True)
    
    return pdf.output(dest='S').encode('latin-1')

# --- STREAMLIT UI ---
st.set_page_config(page_title="PayTrack", page_icon="💸", layout="wide")
init_db()

st.title("💸 PayTrack")
st.markdown("Professional Quote, Invoice & Payment Tracking")

tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "✍️ Create Invoice", "📜 History"])

# --- TAB 1: DASHBOARD ---
with tab1:
    conn = sqlite3.connect('paytrack.db')
    df_history = pd.read_sql_query("SELECT * FROM invoices", conn)
    conn.close()
    
    if not df_history.empty:
        total_invoiced = df_history['total'].sum()
        total_collected = df_history['amount_paid'].sum()
        total_outstanding = df_history['balance'].sum()
        unpaid_count = len(df_history[df_history['status'] != 'Paid'])
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Invoiced", f"R {total_invoiced:,.2f}")
        col2.metric("Total Collected", f"R {total_collected:,.2f}")
        col3.metric("Outstanding", f"R {total_outstanding:,.2f}")
        col4.metric("Unpaid Invoices", unpaid_count)
    else:
        st.info("No invoices generated yet. Create your first invoice to see metrics.")

# --- TAB 2: CREATE INVOICE ---
with tab2:
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.subheader("Business Profile")
        b_name = st.text_input("Business Name")
        b_phone = st.text_input("Business Phone")
        b_email = st.text_input("Business Email")
        b_address = st.text_area("Business Address (Optional)", height=68)
        
    with col_b:
        st.subheader("Customer Info")
        c_name = st.text_input("Customer Name")
        c_phone = st.text_input("Customer Phone")
        c_email = st.text_input("Customer Email")
        inv_date = st.date_input("Invoice Date", datetime.today())

    st.markdown("---")
    st.subheader("Items / Services")
    
    if 'line_items' not in st.session_state:
        st.session_state.line_items = pd.DataFrame([{"Description": "", "Quantity": 1, "Unit Price": 0.0}])
        
    edited_df = st.data_editor(st.session_state.line_items, num_rows="dynamic", use_container_width=True)
    
    # Calculate totals
    items_list = edited_df.to_dict('records')
    for item in items_list:
        item['Total'] = item.get('Quantity', 0) * item.get('Unit Price', 0.0)
        
    total_amount = sum(item['Total'] for item in items_list if item['Description'].strip())
    
    col_tot1, col_tot2 = st.columns(2)
    with col_tot1:
        st.metric("Total Amount", f"R {total_amount:.2f}")
    with col_tot2:
        amount_paid = st.number_input("Amount Paid (R)", min_value=0.0, max_value=float(total_amount), value=0.0, step=10.0)
        
    balance = total_amount - amount_paid
    if amount_paid >= total_amount and total_amount > 0:
        status = "Paid"
    elif amount_paid > 0:
        status = "Partially Paid"
    else:
        status = "Unpaid"
        
    st.markdown(f"**Outstanding Balance:** R {balance:.2f}  |  **Status:** {status}")

    if st.button("Generate Invoice & Save", type="primary"):
        if not b_name or not c_name:
            st.error("Business Name and Customer Name are required.")
        elif total_amount == 0:
            st.error("Please add at least one valid line item.")
        else:
            inv_num = get_next_invoice_number()
            
            invoice_data = {
                'inv_number': inv_num,
                'date': inv_date.strftime("%Y-%m-%d"),
                'b_name': b_name, 'b_phone': b_phone, 'b_email': b_email, 'b_address': b_address,
                'c_name': c_name, 'c_phone': c_phone, 'c_email': c_email,
                'total': total_amount, 'amount_paid': amount_paid, 'balance': balance,
                'status': status, 'items': items_list
            }
            
            save_invoice(invoice_data)
            pdf_bytes = create_pdf(invoice_data)
            
            st.success(f"Invoice {inv_num} saved successfully!")
            
            # PDF Download
            st.download_button(
                label="📄 Download PDF Invoice",
                data=pdf_bytes,
                file_name=f"{inv_num}_{c_name.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
            
            # WhatsApp Message
            wa_msg = f"Hi {c_name}, your invoice {inv_num} totals R{total_amount:.2f}. We have received R{amount_paid:.2f} and the outstanding balance is R{balance:.2f}. Thank you."
            st.info("📱 WhatsApp Payment Message:")
            st.code(wa_msg, language="text")

# --- TAB 3: HISTORY ---
with tab3:
    st.subheader("Invoice History")
    if not df_history.empty:
        display_df = df_history[['inv_number', 'date', 'c_name', 'total', 'amount_paid', 'balance', 'status']]
        display_df.columns = ['Invoice #', 'Date', 'Customer', 'Total (R)', 'Paid (R)', 'Balance (R)', 'Status']
        
        # Color code statuses
        def color_status(val):
            color = 'green' if val == 'Paid' else 'orange' if val == 'Partially Paid' else 'red'
            return f'color: {color}; font-weight: bold'
            
        st.dataframe(display_df.style.applymap(color_status, subset=['Status']), use_container_width=True)
    else:
        st.write("No invoices found.")