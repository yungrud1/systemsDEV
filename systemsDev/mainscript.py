import csv
from collections import defaultdict
import tkinter as tk
from tkinter import filedialog, scrolledtext

# For plotting
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ----------------------
# Data Classes
# ----------------------
class House:
    def __init__(self, house_number):
        self.house_number = house_number
        # Each product is a dict: {"product": str, "quantity": int, "cost": float, "stores": set}
        self.products = []

    def add_product(self, product_name, quantity, cost, store_list):
        if quantity:
            self.products.append({
                "product": product_name,
                "quantity": quantity,
                "cost": cost,  
                "stores": store_list
            })

class Store:
    def __init__(self, store_name):
        self.store_name = store_name
        self.products = set()

    def add_product(self, product_name):
        self.products.add(product_name)

class ScheduleAction:
    """
    Represents one action in the schedule:
      action_type in {"STORE","DELIVER"}
      items: list of "Product xQty"
      store: store name (e.g. "STORE A")
    """
    def __init__(self, action_type, items, store):
        self.action_type = action_type
        self.items = items
        self.store = store

    def __repr__(self):
        return f"ScheduleAction({self.action_type}, {self.items}, {self.store})"

# ----------------------
# CSV Loading
# ----------------------
def load_stores(filename):
    stores = {}
    with open(filename, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        headers = next(reader)
        store_columns = [col for col in headers[3:] if col.strip() != ""]
        for s_name in store_columns:
            stores[s_name] = Store(s_name)
        for row in reader:
            if len(row) >= len(headers):
                product = row[1].strip()
                for i, store_name in enumerate(headers[3:]):
                    store_name = store_name.strip()
                    if store_name and row[3+i].strip().upper() == 'Y':
                        stores[store_name].add_product(product)
    return stores

def load_product_costs(filename):
    costs = {}
    with open(filename, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        _ = next(reader)  # skip header
        for row in reader:
            if len(row) >= 3:
                product = row[1].strip()
                cost_str = row[2].strip().replace("£", "").replace("Ł", "").replace("�", "").strip()
                try:
                    cost = float(cost_str)
                except:
                    cost = 0.0
                costs[product] = cost
    return costs

def load_house_orders(filename, stores, product_costs):
    houses = {}
    with open(filename, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        header = next(reader)

        if len(header) > 1 and not header[1].strip():
            house_nums = [col for col in header[2:] if col.strip()]
            offset = 2
        else:
            house_nums = [col for col in header[1:] if col.strip()]
            offset = 1

        next(reader)  # skip second header row
        for row in reader:
            if row:
                product = row[0].strip()
                cost = product_costs.get(product, 0.0)
                available = {s_name for s_name, s_obj in stores.items() if product in s_obj.products}

                for i, house_id in enumerate(house_nums):
                    qty_str = row[i+offset].strip() if i+offset < len(row) else ''
                    if qty_str.isdigit():
                        qty = int(qty_str)
                        if qty>0:
                            if house_id not in houses:
                                houses[house_id] = House(house_id)
                            houses[house_id].add_product(product, qty, cost, available)
    return houses

# ----------------------
# Build Store -> Day + Priority
# ----------------------
def build_fixed_schedule(stores):
    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    schedule_map = {}
    i=0
    for s_name in stores.keys():
        if i<len(day_names):
            schedule_map[s_name] = day_names[i]
        else:
            schedule_map[s_name] = f"Extra Day {i - len(day_names) +1}"
        i+=1
    return schedule_map

def build_fixed_order(stores):
    order_map={}
    i=1
    for s_name in stores.keys():
        order_map[s_name]=i
        i+=1
    return order_map

# ----------------------
# House Chain + Pairing
# ----------------------
def compute_house_chain(house, stores, fixed_order):
    from collections import defaultdict
    chain_map=defaultdict(list)
    for pr in house.products:
        product=pr["product"]
        qty=pr["quantity"]
        cands=pr["stores"]
        best_s=None
        best_p=float('inf')
        for s in cands:
            p=fixed_order.get(s,9999)
            if p<best_p:
                best_p=p
                best_s=s
        if best_s and qty>0:
            chain_map[best_s].append(f"{product} x{qty}")

    out=sorted(chain_map.items(), key=lambda x: fixed_order[x[0]])
    return out

def build_house_schedule(house, chain, fixed_schedule):
    """
    Pair logic:
      If 1 store => store+deliver same day
      If 2 => day0: store, day1: store+deliver(S0+S1)
      If leftover => store+deliver same day
    """
    from collections import defaultdict
    schedule=defaultdict(list)
    n=len(chain)
    i=0
    while i<n:
        if i == n-1:
            # leftover single store => store+deliver same day
            store_name, items_list=chain[i]
            day_name=fixed_schedule[store_name]
            if items_list:
                schedule[day_name].append(ScheduleAction("STORE", items_list, store_name))
                schedule[day_name].append(ScheduleAction("DELIVER", items_list, store_name))
            i+=1
        else:
            # we have pairs (S0,S1)
            s0_name, s0_items=chain[i]
            s1_name, s1_items=chain[i+1]
            day0=fixed_schedule[s0_name]
            day1=fixed_schedule[s1_name]
            if s0_items:
                schedule[day0].append(ScheduleAction("STORE", s0_items, s0_name))

            # On day1 => store s1 + deliver s0 & s1 combined
            combined=[]
            if s0_items:
                combined.extend(s0_items)
            if s1_items:
                schedule[day1].append(ScheduleAction("STORE", s1_items, s1_name))
                combined.extend(s1_items)
            if combined:
                # single deliver action for s0 + s1
                schedule[day1].append(ScheduleAction("DELIVER", combined, f"{s0_name}+{s1_name}"))
            i+=2
    return schedule

def build_overall_schedule(houses, stores, fixed_order, fixed_schedule):
    from collections import defaultdict
    overall=defaultdict(lambda: defaultdict(list))
    for h_id,h_obj in houses.items():
        chain=compute_house_chain(h_obj, stores, fixed_order)
        h_sched=build_house_schedule(h_obj, chain, fixed_schedule)
        for day_name, acts in h_sched.items():
            for a in acts:
                overall[day_name][h_id].append(a)
    return overall

# ----------------------
# Cost Functions
# ----------------------
def compute_total_cost(houses):
    total=0.0
    for h in houses.values():
        for pr in h.products:
            total += pr["cost"]*pr["quantity"]
    return total

def compute_costs(houses, fixed_order):
    house_costs={}
    store_costs={}
    for h in houses.values():
        h_total=0.0
        for pr in h.products:
            cost=pr["cost"]
            qty=pr["quantity"]
            h_total += cost*qty
            # find best store
            cands=pr["stores"]
            best_s=None
            best_p=float('inf')
            for s in cands:
                p=fixed_order.get(s,9999)
                if p<best_p:
                    best_p=p
                    best_s=s
            if best_s:
                store_costs[best_s] = store_costs.get(best_s,0.0)+cost*qty
        house_costs[h.house_number]=h_total
    return house_costs, store_costs

# ----------------------
# Summaries
# ----------------------
DAY_LIST=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
def day_sort_key(day):
    if day in DAY_LIST:
        return DAY_LIST.index(day)+1
    if day.startswith("Extra Day"):
        parts=day.split()
        if len(parts)==3:
            try:
                return 7+int(parts[2])
            except:
                return 9999
        return 9999
    return 9999

def get_weekly_plan(overall, fixed_schedule):
    all_days=sorted(overall.keys(), key=day_sort_key)
    inv_map={v:k for k,v in fixed_schedule.items()}
    lines=["Weekly Shopping Plan:"]
    for day in all_days:
        store="(No store assigned)"
        if day in inv_map:
            store=inv_map[day]
        lines.append(f"{day}: Visit {store}")
        for h_id in sorted(overall[day].keys()):
            actions=overall[day][h_id]
            act_types=[]
            for a in actions:
                if a.action_type=="STORE":
                    act_types.append("Store")
                else:
                    act_types.append("Deliver")
            lines.append(f"  - {h_id} ({', '.join(act_types)})")
    return "\n".join(lines)

def get_consolidated_shopping_list(overall):
    from collections import defaultdict
    store_items=defaultdict(lambda: defaultdict(int))
    for day, day_houses in overall.items():
        for h_id, actions in day_houses.items():
            for a in actions:
                if a.action_type=="STORE":
                    for item_str in a.items:
                        if " x" in item_str:
                            prod, qty_str=item_str.rsplit(" x",1)
                            prod=prod.strip()
                            try: qty=int(qty_str.strip())
                            except: qty=0
                            store_items[a.store][prod]+=qty
    lines=["Consolidated Shopping List per Store:"]
    for s_name in sorted(store_items.keys()):
        lines.append(f"  {s_name}:")
        for prod,qty in store_items[s_name].items():
            lines.append(f"    {prod} x{qty}")
        lines.append("")
    return "\n".join(lines)

def get_shopping_breakdown(overall, fixed_schedule):
    all_days=sorted(overall.keys(), key=day_sort_key)
    lines=["Shopping Breakdown (per day):"]
    for day in all_days:
        lines.append(f"\n{day}:")
        if not overall[day]:
            lines.append("  No orders can be fulfilled")
            continue
        for h_id in sorted(overall[day].keys()):
            lines.append(f"  House {h_id}:")
            for act in overall[day][h_id]:
                items_join=", ".join(act.items)
                lines.append(f"    {act.action_type} ({act.store}): {items_join}")
    return "\n".join(lines)

def get_cost_summary(total_cost, house_costs, store_costs):
    lines=[]
    lines.append(f"Total Cost for the Week: £{total_cost:.2f}\n")
    lines.append("Cost per Household:")
    for h_id in sorted(house_costs.keys()):
        lines.append(f"  House {h_id}: £{house_costs[h_id]:.2f}")
    lines.append("\nCost per Store:")
    for s_name in sorted(store_costs.keys()):
        lines.append(f"  {s_name}: £{store_costs[s_name]:.2f}")
    return "\n".join(lines)

# ----------------------
# Main Processing
# ----------------------
def run_processing(fileA, fileB):
    global GLOBAL_overall, GLOBAL_fixed_schedule, GLOBAL_houses, GLOBAL_store_costs
    stores=load_stores(fileA)
    product_costs=load_product_costs(fileA)
    houses=load_house_orders(fileB, stores, product_costs)

    fixed_schedule=build_fixed_schedule(stores)
    fixed_order=build_fixed_order(stores)

    overall=build_overall_schedule(houses, stores, fixed_order, fixed_schedule)
    total_cost=compute_total_cost(houses)
    house_costs, store_costs=compute_costs(houses, fixed_order)

    GLOBAL_overall=overall
    GLOBAL_fixed_schedule=fixed_schedule
    GLOBAL_houses=houses
    GLOBAL_store_costs=store_costs  # so we can plot costs easily

    lines=[]
    lines.append(get_weekly_plan(overall, fixed_schedule))
    lines.append("\n"+get_consolidated_shopping_list(overall))
    lines.append("\n"+get_shopping_breakdown(overall, fixed_schedule))
    lines.append("\n"+get_cost_summary(total_cost, house_costs, store_costs))
    return "\n".join(lines)

# ----------------------
# Plotting Functions
# ----------------------
def plot_deliveries():
    if not GLOBAL_overall:
        return

    all_days=sorted(GLOBAL_overall.keys(), key=day_sort_key)
    day_labels=[]
    day_deliveries=[]
    for d in all_days:
        deliver_count=0
        for h_actions in GLOBAL_overall[d].values():
            deliver_count+=sum(1 for a in h_actions if a.action_type=="DELIVER")
        day_labels.append(d)
        day_deliveries.append(deliver_count)

    chart_window=tk.Toplevel(root)
    chart_window.title("Deliveries per Day")

    fig=Figure(figsize=(6,4))
    ax=fig.add_subplot(111)
    ax.bar(day_labels, day_deliveries)
    ax.set_title("Number of Deliveries per Day")
    ax.set_xlabel("Day")
    ax.set_ylabel("Deliveries")

    canvas=FigureCanvasTkAgg(fig, master=chart_window)
    canvas.get_tk_widget().pack()
    canvas.draw()

def plot_store_costs():
    """
    Create a bar chart of cost per store (using GLOBAL_store_costs).
    """
    if not GLOBAL_store_costs:
        return

    # Convert to sorted lists for consistent display
    store_names=sorted(GLOBAL_store_costs.keys())
    costs=[GLOBAL_store_costs[s] for s in store_names]

    chart_window=tk.Toplevel(root)
    chart_window.title("Cost per Store")

    fig=Figure(figsize=(6,4))
    ax=fig.add_subplot(111)
    ax.bar(store_names, costs)
    ax.set_title("Cost per Store")
    ax.set_xlabel("Store")
    ax.set_ylabel("Cost (£)")

    canvas=FigureCanvasTkAgg(fig, master=chart_window)
    canvas.get_tk_widget().pack()
    canvas.draw()

# ----------------------
# GUI
# ----------------------
root = tk.Tk()
root.title("Weekly Shopping Planner")

frame=tk.Frame(root)
frame.pack(padx=10, pady=10)

label_fileA = tk.Label(frame, text="No file selected", width=50, anchor="w")
label_fileB = tk.Label(frame, text="No file selected", width=50, anchor="w")

def select_file(label):
    filename=filedialog.askopenfilename(filetypes=[("CSV files","*.csv")])
    label.config(text=filename)
    return filename

btn_fileA=tk.Button(frame, text="Select File A", command=lambda: select_file(label_fileA))
btn_fileA.grid(row=0, column=0, padx=5, pady=5)
label_fileA.grid(row=0, column=1, padx=5, pady=5)

btn_fileB=tk.Button(frame, text="Select File B", command=lambda: select_file(label_fileB))
btn_fileB.grid(row=1, column=0, padx=5, pady=5)
label_fileB.grid(row=1, column=1, padx=5, pady=5)

def process_files():
    fileA=label_fileA.cget("text")
    fileB=label_fileB.cget("text")
    if fileA and fileB and fileA!="No file selected" and fileB!="No file selected":
        output=run_processing(fileA,fileB)
        text_output.delete(1.0, tk.END)
        text_output.insert(tk.END, output)
    else:
        text_output.delete(1.0, tk.END)
        text_output.insert(tk.END,"Please select both File A and File B.")

btn_run=tk.Button(frame, text="Run Planner", command=process_files)
btn_run.grid(row=2, column=0, columnspan=2, pady=10)

btn_plot_deliveries=tk.Button(frame, text="Plot Deliveries", command=plot_deliveries)
btn_plot_deliveries.grid(row=3, column=0, columnspan=2, pady=5)

btn_plot_costs=tk.Button(frame, text="Plot Store Costs", command=plot_store_costs)
btn_plot_costs.grid(row=4, column=0, columnspan=2, pady=5)

text_output=scrolledtext.ScrolledText(root,width=100,height=30)
text_output.pack(padx=10,pady=10)

GLOBAL_overall=None
GLOBAL_fixed_schedule=None
GLOBAL_houses=None
GLOBAL_store_costs=None

root.mainloop()
