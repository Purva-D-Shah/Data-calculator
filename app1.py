import streamlit as st
import pandas as pd
import io
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Meesho Dashboard", layout="wide")

st.title("📊 Meesho Seller Dashboard")
st.markdown("Upload your **Order Report**, **Payment Reports**, and **Cost Sheet** to generate the overview.")

# --- PAYMENT CHECK (KILL SWITCH) ---
deadline = datetime(2025, 12, 30)
if datetime.now() > deadline:
    st.error("⚠️ License Expired.")
    st.stop()

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ Settings")
    
    st.subheader("1. Cost Configuration")
    uploaded_cost_sheet = st.file_uploader("Upload Base Price/Cost Sheet (CSV/Excel)", type=['csv', 'xlsx'], help="File must have 'SKU' and 'Cost' columns.")
    
    st.write("---")
    st.subheader("2. Fallback Values")
    st.info("Used if SKU is not found in the Cost Sheet.")
    fallback_product_cost = st.number_input("Default Product Cost (₹)", value=0.0, step=10.0)
    packaging_cost = st.number_input("Packaging Cost (₹)", value=5.0, step=1.0)

# --- 1. UPLOAD FILES ---
with st.expander("📂 Upload Order & Payment Files", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        uploaded_order = st.file_uploader("Upload Order Report (CSV/Excel)", type=['csv', 'xlsx'])
    with col2:
        uploaded_payments = st.file_uploader("Upload Payment Reports", type=['xlsx'], accept_multiple_files=True)

# --- HELPER FUNCTIONS ---
def normalize_columns(df):
    """Standardizes column names to lowercase, no spaces."""
    df.columns = df.columns.astype(str).str.lower().str.replace(" ", "").str.replace("_", "").str.replace(".", "")
    return df

def find_column(df, keywords):
    """Finds a column containing any of the keywords."""
    for col in df.columns:
        if any(k in col for k in keywords):
            return col
    return None

if st.button("Generate Dashboard"):
    if not uploaded_order or not uploaded_payments:
        st.error("⚠️ Please upload both Order and Payment files.")
    else:
        with st.spinner('Crunching the numbers...'):
            try:
                # ==========================================
                # 1. PROCESS COST SHEET (If Uploaded)
                # ==========================================
                cost_map = {}
                if uploaded_cost_sheet:
                    try:
                        if uploaded_cost_sheet.name.endswith('.csv'):
                            cost_df = pd.read_csv(uploaded_cost_sheet)
                        else:
                            cost_df = pd.read_excel(uploaded_cost_sheet)
                        
                        normalize_columns(cost_df)
                        
                        # Find SKU and Cost columns
                        c_sku = find_column(cost_df, ['sku', 'style', 'design', 'productid'])
                        c_cost = find_column(cost_df, ['cost', 'price', 'rate', 'amount', 'purchase'])
                        
                        if c_sku and c_cost:
                            # Create a dictionary {sku: cost}
                            # Clean SKU: convert to string, strip spaces, lower case for matching
                            cost_df[c_sku] = cost_df[c_sku].astype(str).str.strip().str.lower()
                            cost_df[c_cost] = pd.to_numeric(cost_df[c_cost], errors='coerce').fillna(0)
                            cost_map = pd.Series(cost_df[c_cost].values, index=cost_df[c_sku]).to_dict()
                            st.sidebar.success(f"✅ Loaded {len(cost_map)} SKU costs.")
                        else:
                            st.sidebar.error("❌ Cost sheet must have 'SKU' and 'Cost' columns.")
                    except Exception as e:
                        st.sidebar.error(f"Error reading cost sheet: {e}")

                # ==========================================
                # 2. PROCESS ORDER FILE
                # ==========================================
                if uploaded_order.name.endswith('.csv'):
                    try:
                        orders_df = pd.read_csv(uploaded_order)
                    except:
                        uploaded_order.seek(0)
                        orders_df = pd.read_csv(uploaded_order, encoding='latin1')
                else:
                    orders_df = pd.read_excel(uploaded_order)
                
                normalize_columns(orders_df)
                
                # Find ID Column
                order_id_col = find_column(orders_df, ["suborder", "orderid"])
                if not order_id_col:
                    st.error("❌ Could not find 'Sub Order No' column in Order File.")
                    st.stop()
                orders_df[order_id_col] = orders_df[order_id_col].astype(str)

                # Find SKU Column in Orders (for mapping costs)
                order_sku_col = find_column(orders_df, ["sku", "style", "productid"])

                # Find Order Status Column (Fallback)
                order_status_col = find_column(orders_df, ["orderstatus", "status"])
                
                # ==========================================
                # 3. PROCESS PAYMENT FILES
                # ==========================================
                payment_frames = []
                
                for pay_file in uploaded_payments:
                    try:
                        xls = pd.ExcelFile(pay_file)
                        for sheet in xls.sheet_names:
                            df = pd.read_excel(xls, sheet_name=sheet)
                            if len(df) < 2: continue 

                            # Header fix
                            temp_cols = df.columns.astype(str).str.lower().str.replace(" ", "")
                            if "suborder" not in str(list(temp_cols)) and len(df) > 2:
                                try: df = pd.read_excel(xls, sheet_name=sheet, header=1)
                                except: pass
                            
                            normalize_columns(df)
                            
                            p_id = find_column(df, ["suborder"])
                            p_amt = find_column(df, ["finalsettlement", "settlementamount", "netamount"])
                            p_status = find_column(df, ["liveorderstatus", "orderstatus"]) 
                            
                            if p_id and p_amt:
                                df = df.rename(columns={p_id: 'suborderno', p_amt: 'amount'})
                                df = df.dropna(subset=['suborderno'])
                                df['suborderno'] = df['suborderno'].astype(str)
                                
                                cols_to_keep = ['suborderno', 'amount']
                                if p_status:
                                    df = df.rename(columns={p_status: 'payment_status'})
                                    cols_to_keep.append('payment_status')
                                
                                payment_frames.append(df[cols_to_keep])
                    except: pass

                if payment_frames:
                    all_payments = pd.concat(payment_frames)
                    all_payments['amount'] = pd.to_numeric(all_payments['amount'], errors='coerce').fillna(0)
                    
                    amount_summary = all_payments.groupby("suborderno")["amount"].sum().reset_index()
                    
                    if 'payment_status' in all_payments.columns:
                        status_summary = all_payments.dropna(subset=['payment_status']).drop_duplicates('suborderno', keep='last')[['suborderno', 'payment_status']]
                        payment_summary = pd.merge(amount_summary, status_summary, on='suborderno', how='left')
                    else:
                        payment_summary = amount_summary
                        payment_summary['payment_status'] = None
                else:
                    payment_summary = pd.DataFrame(columns=["suborderno", "amount", "payment_status"])

                # ==========================================
                # 4. MERGE & CALCULATE
                # ==========================================
                final_df = pd.merge(orders_df, payment_summary, left_on=order_id_col, right_on="suborderno", how="left")
                final_df["amount"] = final_df["amount"].fillna(0)
                
                # --- STATUS LOGIC ---
                def get_final_status(row):
                    if pd.notna(row.get('payment_status')): return str(row['payment_status']).lower()
                    if order_status_col and pd.notna(row.get(order_status_col)): return str(row[order_status_col]).lower()
                    return "unknown"
                final_df['final_status'] = final_df.apply(get_final_status, axis=1)

                # --- COST LOGIC ---
                # 1. Determine Unit Cost based on SKU
                def get_unit_cost(row):
                    if not order_sku_col: return fallback_product_cost
                    sku_val = str(row.get(order_sku_col, "")).strip().lower()
                    # Return mapped cost if exists, else fallback
                    return cost_map.get(sku_val, fallback_product_cost)

                final_df['unit_cost'] = final_df.apply(get_unit_cost, axis=1)

                # 2. Apply Cost ONLY if status is Delivered, Exchange, or Return
                valid_cost_statuses = ['delivered', 'exchange', 'return', 'customer return']
                
                def calculate_total_cost(row):
                    status = row['final_status']
                    if any(x in status for x in valid_cost_statuses):
                        # Cost = Unit Cost * Quantity
                        qty = pd.to_numeric(row.get('quantity', 1), errors='coerce') # Handle missing qty
                        if pd.isna(qty): qty = 1
                        return row['unit_cost'] * qty
                    return 0.0

                final_df["Product Cost"] = final_df.apply(calculate_total_cost, axis=1)
                
                # 3. Packaging & Net Profit
                final_df["Packaging Cost"] = packaging_cost
                final_df["Net_Profit"] = final_df["amount"] - final_df["Product Cost"] - final_df["Packaging Cost"]

                # ==========================================
                # 5. METRICS & DISPLAY
                # ==========================================
                total_orders = len(final_df)
                payout_settled = final_df['amount'].sum()
                total_product_cost = final_df['Product Cost'].sum()
                total_profit = final_df['Net_Profit'].sum()

                # Calculate counts
                def count_status_final(keywords):
                    mask = final_df['final_status'].str.contains('|'.join(keywords), na=False)
                    return len(final_df[mask])
                
                delivered = count_status_final(['delivered'])
                returned = count_status_final(['return', 'customerreturn'])
                rtos = count_status_final(['rto', 'undelivered'])
                cancelled = count_status_final(['cancel'])

                st.markdown("### 📈 Profitability Overview")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Settlement", f"₹ {payout_settled:,.2f}")
                m2.metric("Total Product Cost", f"₹ {total_product_cost:,.2f}")
                m3.metric("Net Profit / Loss", f"₹ {total_profit:,.2f}", delta_color="normal")
                m4.metric("Avg Profit per Order", f"₹ {total_profit/total_orders:,.2f}" if total_orders else "0")

                st.markdown("---")
                st.markdown("### 📦 Order Status Counts")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Delivered", delivered)
                c2.metric("Returned", returned)
                c3.metric("RTO", rtos)
                c4.metric("Cancelled", cancelled)

                # ==========================================
                # 6. DOWNLOAD
                # ==========================================
                st.markdown("---")
                with st.expander("📄 View Detailed Reconciliation Data"):
                    # Show readable columns
                    display_cols = [order_id_col, 'final_status', order_sku_col] if order_sku_col else [order_id_col, 'final_status']
                    display_cols += ['amount', 'unit_cost', 'Product Cost', 'Net_Profit']
                    
                    st.dataframe(final_df[display_cols])
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        final_df.to_excel(writer, index=False)
                    st.download_button("📥 Download Final Report", buffer, "Meesho_Reconciliation_Final.xlsx")

            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.exception(e)
