#!/usr/bin/env python3
"""
Script to add OpenTelemetry instrumentation to a FlowCore service.
Usage: python scripts/instrument_service.py <service_name>
Example: python scripts/instrument_service.py dcim-ingestion
"""
import sys
import os
import re


def instrument_service(service_dir: str):
    """Add telemetry instrumentation to a service's main.py."""
    main_file = os.path.join("services", service_dir, "main.py")

    if not os.path.exists(main_file):
        print(f"❌ Service not found: {main_file}")
        return False

    with open(main_file, 'r') as f:
        content = f.read()

    # Check if already instrumented
    if 'import telemetry' in content:
        print(f"✅ Service already instrumented: {service_dir}")
        return True

    # Find service name from directory
    service_name = service_dir.replace('-', '_')

    # Prepare the telemetry import block
    telemetry_block = f'''import sys
import os
# Add parent directory to path for shared telemetry module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telemetry

# Setup OpenTelemetry for SigNoz (must be before other imports)
tracer = telemetry.setup_telemetry("{service_dir}")

'''

    # Find the first import statement and insert before it
    lines = content.split('\n')
    import_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('import ') or line.strip().startswith('from '):
            # Skip docstring imports
            if not any(x in line for x in ['"""', "'''"]):
                import_idx = i
                break

    # Insert telemetry block before first import
    new_lines = lines[:import_idx] + telemetry_block.split('\n') + lines[import_idx:]

    # Find FastAPI app creation and add instrumentation
    content = '\n'.join(new_lines)

    # Add instrument_fastapi after app creation
    app_pattern = r'(app = FastAPI\([^)]+\)\n)'
    if re.search(app_pattern, content):
        content = re.sub(
            app_pattern,
            r'\1\n# Instrument FastAPI for automatic tracing\ntelemetry.instrument_fastapi(app, tracer)\n',
            content
        )

    # Remove duplicate logging.basicConfig if present
    content = re.sub(
        r'logging\.basicConfig\([^)]+\)\n?',
        '',
        content
    )

    # Write back
    with open(main_file, 'w') as f:
        f.write(content)

    print(f"✅ Instrumented: {service_dir}")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/instrument_service.py <service_name>")
        print("Example: python scripts/instrument_service.py dcim-ingestion")
        print("\nTo instrument all services:")
        print("  python scripts/instrument_service.py --all")
        sys.exit(1)

    if sys.argv[1] == '--all':
        services = [d for d in os.listdir('services') if os.path.isdir(os.path.join('services', d))]
        success = 0
        for svc in services:
            if instrument_service(svc):
                success += 1
        print(f"\n📊 Instrumented {success}/{len(services)} services")
    else:
        instrument_service(sys.argv[1])


if __name__ == "__main__":
    main()
