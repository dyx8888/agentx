"""
Modification Rate Checker for Self-Evolution Monitoring
Analyzes feedback data to identify tools that need fine-tuning
"""

import argparse
import logging
import os
import sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler


# Setup logging
def setup_logging():
    """Setup logging configuration"""
    # Get project root directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    log_dir = os.path.join(project_root, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "evolution.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(log_file, encoding='utf-8', maxBytes=10*1024*1024, backupCount=5),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)

logger = setup_logging()

class ModificationRateChecker:
    """Analyzes feedback modification rates and triggers alerts"""

    def __init__(self, db_path: str = None):
        # Use absolute path based on project root
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir)
            db_path = os.path.join(project_root, "data", "feedback.db")
        self.db_path = db_path
        self.modification_threshold = 40.0  # 40% modification rate threshold
        self.consecutive_days_threshold = 3  # 3 consecutive days

    def check_modification_rates(self) -> list[dict]:
        """Check modification rates for recent days"""
        try:
            # Get modification rates for last 7 days
            rates = self.get_daily_modification_rates(7)

            # Check for tools that exceed thresholds
            alerts = []
            for tool_name, daily_rates in rates.items():
                if self.check_consecutive_high_modification(daily_rates):
                    total_modifications = sum(rate['modified_count'] for rate in daily_rates)
                    alerts.append({
                        'tool_name': tool_name,
                        'daily_rates': daily_rates,
                        'total_modifications': total_modifications,
                        'alert_level': 'HIGH'
                    })

            return alerts

        except Exception as e:
            logger.error(f"Error checking modification rates: {e}")
            return []

    def get_daily_modification_rates(self, days: int) -> dict[str, list[dict]]:
        """Get daily modification rates for each tool"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get daily stats for each tool
                cursor.execute(f"""
                    SELECT 
                        tool_name,
                        DATE(created_at) as date,
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN original_output != human_edited_output THEN 1 END) as modified_count,
                        COUNT(CASE WHEN original_output = human_edited_output THEN 1 END) as adopted_count
                    FROM feedback
                    WHERE created_at >= date('now', '-{days} days')
                    GROUP BY tool_name, DATE(created_at)
                    ORDER BY tool_name, date DESC
                """)

                results = cursor.fetchall()

                # Organize results by tool
                tool_rates = {}
                for tool_name, date, total, modified, adopted in results:
                    if tool_name not in tool_rates:
                        tool_rates[tool_name] = []

                    modification_rate = (modified / total * 100) if total > 0 else 0

                    tool_rates[tool_name].append({
                        'date': date,
                        'total_feedback': total,
                        'modified_count': modified,
                        'adopted_count': adopted,
                        'modification_rate': round(modification_rate, 2)
                    })

                return tool_rates

        except Exception as e:
            logger.error(f"Error getting daily modification rates: {e}")
            return {}

    def check_consecutive_high_modification(self, daily_rates: list[dict]) -> bool:
        """Check if a tool has consecutive high modification rates"""
        if len(daily_rates) < self.consecutive_days_threshold:
            return False

        # Check most recent consecutive days
        recent_rates = daily_rates[:self.consecutive_days_threshold]

        consecutive_high = 0
        for rate in recent_rates:
            if rate['modification_rate'] > self.modification_threshold:
                consecutive_high += 1
            else:
                break

        return consecutive_high >= self.consecutive_days_threshold

    def generate_evolution_report(self) -> str:
        """Generate a comprehensive evolution report"""
        try:
            alerts = self.check_modification_rates()

            report = f"""
=== Self-Evolution Report ===
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

SUMMARY:
- Tools monitored: {len(self.get_daily_modification_rates(7))}
- Tools needing attention: {len(alerts)}
- Modification threshold: {self.modification_threshold}%
- Consecutive days threshold: {self.consecutive_days_threshold}

ALERTS:
"""

            if alerts:
                for alert in alerts:
                    tool_name = alert['tool_name']
                    total_modifications = alert['total_modifications']

                    report += f"""
TRIGGER FINE-TUNING: {tool_name}
- Modification rate exceeded threshold for {self.consecutive_days_threshold} consecutive days
- Total modifications: {total_modifications} pairs
- Recent daily rates:
"""

                    for rate in alert['daily_rates'][:self.consecutive_days_threshold]:
                        report += f"  * {rate['date']}: {rate['modification_rate']}% ({rate['modified_count']}/{rate['total_feedback']})\n"

                    report += "\n"
            else:
                report += "No tools exceeded modification thresholds. All systems performing well.\n"

            # Add overall statistics
            overall_stats = self.get_overall_statistics()
            report += f"""
OVERALL STATISTICS (Last 7 Days):
- Total feedback pairs: {overall_stats['total_feedback']}
- Overall modification rate: {overall_stats['overall_modification_rate']}%
- Most modified tool: {overall_stats['most_modified_tool']}
- Best performing tool: {overall_stats['best_performing_tool']}

RECOMMENDATIONS:
"""

            if alerts:
                report += """
1. Review and fine-tune identified tools
2. Analyze common modification patterns
3. Update knowledge base with successful modifications
4. Consider adjusting prompts or model parameters
"""
            else:
                report += """
1. Continue monitoring performance
2. Collect more feedback for better insights
3. Maintain current configuration
"""

            return report

        except Exception as e:
            logger.error(f"Error generating evolution report: {e}")
            return f"Error generating report: {str(e)}"

    def get_overall_statistics(self) -> dict:
        """Get overall statistics for last 7 days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Overall stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN original_output != human_edited_output THEN 1 END) as modified_count,
                        COUNT(CASE WHEN original_output = human_edited_output THEN 1 END) as adopted_count
                    FROM feedback
                    WHERE created_at >= date('now', '-7 days')
                """)

                total, modified, adopted = cursor.fetchone()
                overall_modification_rate = (modified / total * 100) if total > 0 else 0

                # Most modified tool
                cursor.execute("""
                    SELECT tool_name, COUNT(CASE WHEN original_output != human_edited_output THEN 1 END) as modifications
                    FROM feedback
                    WHERE created_at >= date('now', '-7 days')
                    GROUP BY tool_name
                    ORDER BY modifications DESC
                    LIMIT 1
                """)

                most_modified_result = cursor.fetchone()
                most_modified_tool = most_modified_result[0] if most_modified_result else 'N/A'

                # Best performing tool
                cursor.execute("""
                    SELECT 
                        tool_name, 
                        COUNT(CASE WHEN original_output = human_edited_output THEN 1 END) as adopted,
                        COUNT(*) as total
                    FROM feedback
                    WHERE created_at >= date('now', '-7 days')
                    GROUP BY tool_name
                    HAVING total >= 5
                    ORDER BY (CAST(adopted AS FLOAT) / total) DESC
                    LIMIT 1
                """)

                best_result = cursor.fetchone()
                best_performing_tool = best_result[0] if best_result else 'N/A'

                return {
                    'total_feedback': total,
                    'overall_modification_rate': round(overall_modification_rate, 2),
                    'most_modified_tool': most_modified_tool,
                    'best_performing_tool': best_performing_tool
                }

        except Exception as e:
            logger.error(f"Error getting overall statistics: {e}")
            return {}

def main():
    """Main function to run modification rate checker"""
    parser = argparse.ArgumentParser(description='Check modification rates and trigger evolution')
    parser.add_argument('--generate-training', action='store_true',
                       help='Generate training data and trigger evolution')
    args = parser.parse_args()

    logger.info("Starting modification rate checker...")

    try:
        checker = ModificationRateChecker()

        if args.generate_training:
            logger.info("Generating training data and triggering evolution...")
            # Import and trigger evolution scheduler
            import sys
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from app.evolution.scheduler import EvolutionScheduler

            scheduler = EvolutionScheduler()
            scheduler.check_and_trigger_evolution()
            logger.info("Training data generation and evolution check completed")
            return

        # Check for alerts
        alerts = checker.check_modification_rates()

        if alerts:
            for alert in alerts:
                tool_name = alert['tool_name']
                total_modifications = alert['total_modifications']

                alert_message = f"TRIGGER FINE-TUNING: {tool_name}  modification rate too high, cumulative modifications: {total_modifications} pairs"
                logger.warning(alert_message)
                print(f"ALERT: {alert_message}")

        # Generate and log full report
        report = checker.generate_evolution_report()
        logger.info("Evolution report generated")
        print(report)

    except Exception as e:
        logger.error(f"Error in main function: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
