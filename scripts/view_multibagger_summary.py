#!/usr/bin/env python3
"""
Quick Start Guide for Multi-Bagger Analysis
Run this to see a summary of results
"""
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

def main():
    # Load data
    data_file = Path(__file__).parent.parent / "data" / "multibagger_analysis_report.json"
    
    if not data_file.exists():
        console.print("[red]❌ Analysis data not found. Run analysis first:[/red]")
        console.print("[yellow]python scripts/multibagger_analysis.py[/yellow]")
        return
    
    with open(data_file, 'r') as f:
        data = json.load(f)
    
    # Header
    console.print()
    console.print(Panel.fit(
        "🚀 [bold cyan]MULTI-BAGGER ANALYSIS - QUICK SUMMARY[/bold cyan] 🚀",
        border_style="cyan"
    ))
    console.print()
    
    # Winners summary
    winners = data.get('historical_winners', [])
    console.print(f"[green]✅ Found {len(winners)} multi-bagger stocks (200%+ returns)[/green]")
    console.print(f"[blue]📊 Average Return: {sum(w['return_pct'] for w in winners)/len(winners):.1f}%[/blue]")
    console.print()
    
    # Top 5 winners
    console.print("[bold yellow]🏆 TOP 5 HISTORICAL WINNERS:[/bold yellow]")
    winners_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    winners_table.add_column("#", style="dim", width=3)
    winners_table.add_column("Stock", style="cyan", width=12)
    winners_table.add_column("Return", justify="right", style="green")
    winners_table.add_column("Sector", style="blue")
    winners_table.add_column("Rev Growth", justify="right")
    winners_table.add_column("ROE", justify="right")
    
    for i, winner in enumerate(sorted(winners, key=lambda x: x['return_pct'], reverse=True)[:5], 1):
        winners_table.add_row(
            str(i),
            winner['symbol'],
            f"+{winner['return_pct']:.1f}%",
            winner['sector'],
            f"{winner.get('revenue_growth', 0):.1f}%",
            f"{winner.get('roe', 0):.1f}%"
        )
    
    console.print(winners_table)
    console.print()
    
    # Top 10 prospects
    prospects = data.get('prospects', [])
    console.print(f"[bold yellow]🎯 TOP 10 HIGH-POTENTIAL PROSPECTS:[/bold yellow]")
    
    # Sort and get top 10
    prospects_sorted = sorted(
        prospects,
        key=lambda x: x.get('total_score', x.get('score', 0)),
        reverse=True
    )[:10]
    
    prospects_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    prospects_table.add_column("#", style="dim", width=3)
    prospects_table.add_column("Stock", style="cyan", width=12)
    prospects_table.add_column("Score", justify="right", style="green")
    prospects_table.add_column("Price", justify="right")
    prospects_table.add_column("Sector", style="blue")
    prospects_table.add_column("Market Cap", justify="right")
    
    for i, prospect in enumerate(prospects_sorted, 1):
        score = prospect.get('total_score', prospect.get('score', 0))
        prospects_table.add_row(
            str(i),
            prospect['symbol'],
            f"{score:.0f}/100",
            f"₹{prospect.get('current_price', 0):.2f}",
            prospect['sector'],
            f"₹{prospect.get('market_cap_cr', prospect.get('market_cap', 0)):,.0f}Cr"
        )
    
    console.print(prospects_table)
    console.print()
    
    # Key insights
    console.print(Panel(
        "[bold cyan]💡 KEY INSIGHTS:[/bold cyan]\n\n"
        f"• [green]Top Sectors:[/green] FMCG, Technology, Pharma\n"
        f"• [green]Ideal Market Cap:[/green] ₹10,000 - ₹50,000 Cr\n"
        f"• [green]Target Rev Growth:[/green] >20% YoY\n"
        f"• [green]Minimum ROE:[/green] >15%\n"
        f"• [green]Best Entry:[/green] Breakout with volume confirmation",
        title="Success Pattern",
        border_style="yellow"
    ))
    console.print()
    
    # Next steps
    console.print("[bold cyan]📋 NEXT STEPS:[/bold cyan]")
    console.print("1. [yellow]View Interactive Dashboard:[/yellow]")
    console.print("   streamlit run ui/multibagger_dashboard.py --server.port 8502")
    console.print()
    console.print("2. [yellow]Deep Dive Research:[/yellow]")
    console.print("   Focus on top 3-5 prospects for fundamental analysis")
    console.print()
    console.print("3. [yellow]Setup Alerts:[/yellow]")
    console.print("   Add prospects to watchlist and monitor for entry setups")
    console.print()
    console.print("4. [yellow]Paper Trade:[/yellow]")
    console.print("   Test strategies on these stocks before going live")
    console.print()
    
    console.print("[dim]Report location: data/multibagger_analysis_report.json[/dim]")
    console.print("[dim]Documentation: docs/MULTIBAGGER_ANALYSIS.md[/dim]")
    console.print()

if __name__ == "__main__":
    main()
