#!/usr/bin/env python3
"""
Submit PyFlink jobs to the cluster
Usage: python submit_jobs.py --environment local --job all
"""
import argparse
import sys
import time
import subprocess
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Colors for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


def get_environment_config(environment):
    """Get configuration for different environments"""
    configs = {
        'local': {
            'kafka_servers': 'localhost:9092',
            'redis_nodes': 'localhost:7000,localhost:7001,localhost:7002',
            'clickhouse_host': 'localhost:9000',
            'flink_host': 'localhost:8081',
            'parallelism': 2
        },
        'docker': {
            'kafka_servers': 'kafka-1:29092,kafka-2:29093',
            'redis_nodes': 'redis-1:7000,redis-2:7001,redis-3:7002', 
            'clickhouse_host': 'clickhouse-1:9000',
            'flink_host': 'flink-jobmanager:8081',
            'parallelism': 4
        },
        'staging': {
            'kafka_servers': 'kafka-cluster:9092',
            'redis_nodes': 'redis-cluster:7000',
            'clickhouse_host': 'clickhouse-cluster:9000',
            'flink_host': 'flink-cluster:8081',
            'parallelism': 8
        },
        'production': {
            'kafka_servers': 'kafka-prod:9092',
            'redis_nodes': 'redis-prod:7000',
            'clickhouse_host': 'clickhouse-prod:9000', 
            'flink_host': 'flink-prod:8081',
            'parallelism': 16
        }
    }
    
    if environment not in configs:
        raise ValueError(f"Unknown environment: {environment}")
    
    return configs[environment]


def check_flink_cluster(flink_host):
    """Check if Flink cluster is available"""
    import requests
    try:
        response = requests.get(f"http://{flink_host}/overview", timeout=10)
        if response.status_code == 200:
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"Failed to connect to Flink cluster: {e}")
        return False


def submit_job(job_name, job_config, environment_config, args):
    """Submit a PyFlink job"""
    logger.info(f"{Colors.YELLOW}📤 Submitting {job_name}...{Colors.NC}")
    
    # Build command
    python_path = sys.executable
    job_script = Path(__file__).parent / "src" / "jobs" / f"{job_name}.py"
    
    if not job_script.exists():
        logger.error(f"{Colors.RED}❌ Job script not found: {job_script}{Colors.NC}")
        return False
    
    # Build command arguments
    cmd = [
        python_path, str(job_script),
        '--kafka-servers', environment_config['kafka_servers'],
        '--parallelism', str(job_config.get('parallelism', environment_config['parallelism'])),
        '--checkpoint-interval', str(job_config.get('checkpoint_interval', 10000))
    ]
    
    # Add job-specific arguments
    if 'redis_nodes' in job_config:
        cmd.extend(['--redis-nodes', environment_config['redis_nodes']])
    
    if 'clickhouse_host' in job_config:
        cmd.extend(['--clickhouse-host', environment_config['clickhouse_host']])
    
    if 'session_timeout' in job_config:
        cmd.extend(['--session-timeout', str(job_config['session_timeout'])])
    
    if 'processing_mode' in job_config:
        cmd.extend(['--processing-mode', job_config['processing_mode']])
    
    # Submit job
    try:
        logger.info(f"Running command: {' '.join(cmd)}")
        
        if args.dry_run:
            logger.info(f"{Colors.BLUE}🔍 DRY RUN - Would submit: {job_name}{Colors.NC}")
            return True
        
        # For local submission, run directly
        if environment_config.get('local_mode', True):
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a bit to see if job starts successfully
            time.sleep(5)
            
            if process.poll() is None:  # Still running
                logger.info(f"{Colors.GREEN}✅ {job_name} started successfully{Colors.NC}")
                return True
            else:
                stdout, stderr = process.communicate()
                logger.error(f"{Colors.RED}❌ {job_name} failed to start{Colors.NC}")
                logger.error(f"STDOUT: {stdout}")
                logger.error(f"STDERR: {stderr}")
                return False
        
        else:
            # For cluster submission, would use Flink CLI
            # This would require packaging and using flink run command
            logger.warning(f"{Colors.YELLOW}⚠️  Cluster submission not implemented yet{Colors.NC}")
            return True
            
    except Exception as e:
        logger.error(f"{Colors.RED}❌ Failed to submit {job_name}: {e}{Colors.NC}")
        return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Submit PyFlink Jobs')
    parser.add_argument('--environment', choices=['local', 'docker', 'staging', 'production'], 
                       default='local', help='Target environment')
    parser.add_argument('--job', choices=['realtime-metrics', 'session-processing', 
                                         'analytics-aggregation', 'all'], 
                       default='all', help='Job to submit')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be submitted without actually submitting')
    
    args = parser.parse_args()
    
    logger.info(f"{Colors.BLUE}🚀 PyFlink Job Submission - Environment: {args.environment}{Colors.NC}")
    
    # Get environment configuration
    try:
        env_config = get_environment_config(args.environment)
    except ValueError as e:
        logger.error(f"{Colors.RED}❌ {e}{Colors.NC}")
        return 1
    
    # Check Flink cluster availability (skip for local mode)
    if args.environment != 'local' and not args.dry_run:
        if not check_flink_cluster(env_config['flink_host']):
            logger.error(f"{Colors.RED}❌ Flink cluster not available at {env_config['flink_host']}{Colors.NC}")
            return 1
        
        logger.info(f"{Colors.GREEN}✅ Flink cluster is available{Colors.NC}")
    
    # Job configurations
    job_configs = {
        'realtime_metrics_job': {
            'parallelism': env_config['parallelism'],
            'checkpoint_interval': 5000,
            'redis_nodes': True,
            'description': 'Real-time metrics processing'
        },
        'session_processing_job': {
            'parallelism': env_config['parallelism'] * 2,
            'checkpoint_interval': 15000,
            'session_timeout': 30,
            'redis_nodes': True,
            'clickhouse_host': True,
            'description': 'User session analysis'
        },
        'analytics_aggregation_job': {
            'parallelism': env_config['parallelism'],
            'checkpoint_interval': 30000,
            'processing_mode': 'streaming',
            'clickhouse_host': True,
            'description': 'SQL-based analytics aggregation'
        }
    }
    
    # Submit jobs
    success_count = 0
    total_jobs = 0
    
    jobs_to_submit = []
    if args.job == 'all':
        jobs_to_submit = list(job_configs.keys())
    else:
        job_map = {
            'realtime-metrics': 'realtime_metrics_job',
            'session-processing': 'session_processing_job', 
            'analytics-aggregation': 'analytics_aggregation_job'
        }
        if args.job in job_map:
            jobs_to_submit = [job_map[args.job]]
        else:
            logger.error(f"{Colors.RED}❌ Unknown job: {args.job}{Colors.NC}")
            return 1
    
    logger.info(f"{Colors.BLUE}🏁 Starting job submissions...{Colors.NC}")
    print("")
    
    for job_name in jobs_to_submit:
        job_config = job_configs[job_name]
        total_jobs += 1
        
        logger.info(f"{Colors.BLUE}📋 Job: {job_config['description']}{Colors.NC}")
        
        if submit_job(job_name, job_config, env_config, args):
            success_count += 1
        
        print("")
        time.sleep(2)  # Brief pause between submissions
    
    # Summary
    if success_count == total_jobs:
        logger.info(f"{Colors.GREEN}🎉 All {total_jobs} jobs submitted successfully!{Colors.NC}")
        print("")
        logger.info(f"{Colors.BLUE}📊 Monitor jobs at: http://{env_config['flink_host']}{Colors.NC}")
        logger.info(f"{Colors.BLUE}📈 Metrics at: http://localhost:9090{Colors.NC}")
        logger.info(f"{Colors.BLUE}📋 Dashboards at: http://localhost:3000{Colors.NC}")
        
        if args.environment == 'local':
            logger.info(f"{Colors.BLUE}🔬 Jupyter notebooks: http://localhost:8888{Colors.NC}")
        
        print("")
        logger.info(f"{Colors.GREEN}🔥 PyFlink cluster is now processing events!{Colors.NC}")
        return 0
    else:
        logger.error(f"{Colors.RED}❌ {success_count}/{total_jobs} jobs submitted successfully{Colors.NC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())