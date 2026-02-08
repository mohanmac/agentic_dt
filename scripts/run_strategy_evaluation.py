import sys
import os
from pathlib import Path
import tabulate

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.strategy_engine import StrategyEngine
from app.core.utils import format_pnl

def run_evaluation():
    engine = StrategyEngine()
    strategies = engine.get_strategies()
    
    results_data = []
    
    # User's Table Columns mapping to our internal data
    # Strategy | Win Rate | Profit Factor | Avg Win | Avg Loss | Max DD | Key Metric
    
    print("Running Backtest Evaluation for 7 Strategies...\n")
    
    for i, strategy in enumerate(strategies, 1):
        # Run Backtest
        result = engine.run_backtest(strategy.name, "MCX", days=30)
        
        # Format metrics
        row = {
            "#": i,
            "Strategy": strategy.name,
            "Signal Logic": strategy.description,
            "Win Rate": f"{result.win_rate:.1f}%",
            "Profit Factor": f"{result.profit_factor:.2f}",
            "Avg Win": f"Rs. {result.avg_win:.2f}",
            "Avg Loss": f"Rs. {result.avg_loss:.2f}",
            "Max DD": f"Rs. {result.max_drawdown:.2f}",
            "Key Observation": f"{result.metrics['Primary Metric']}"
        }
        results_data.append(row)
        
    # Print Markdown Table
    headers = ["#", "Strategy", "Win Rate", "Profit Factor", "Avg Win", "Avg Loss", "Max DD", "Key Observation"]
    
    # Header row
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    
    print(header_line)
    print(sep_line)
    
    for r in results_data:
        row_str = "| " + " | ".join([str(r[h]) for h in headers]) + " |"
        print(row_str)
    
    print("\n\n### Detailed Analysis per Strategy\n")
    for r in results_data:
        print(f"**{r['Strategy']}**")
        print(f"- **Logic**: {r['Signal Logic']}")
        print(f"- **Performance**: {r['Win Rate']} Win Rate with {r['Profit Factor']} Profit Factor.")
        print(f"- **Risk Profile**: Max Drawdown of {r['Max DD']}. Avg Loss {r['Avg Loss']}.")
        print(f"- **Observation**: Monitoring {r['Key Observation']}.\n")

if __name__ == "__main__":
    run_evaluation()
