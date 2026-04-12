#!/usr/bin/env python3
"""
FlowCore Neo4j Loader
======================
Streams neo4j_seed.cypher into a running Neo4j 5 instance via the
Bolt Python driver in batches, handling large files gracefully.

Usage:
  python3 neo4j_loader.py \
      --uri  bolt://localhost:7687 \
      --user neo4j \
      --password flowcore_secret \
      --file generators/output/neo4j_seed.cypher

Requirements: pip install neo4j
Falls back to cypher-shell if neo4j driver is not installed.
"""

import sys, os, time, argparse, subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--uri',      default='bolt://localhost:7687')
parser.add_argument('--user',     default='neo4j')
parser.add_argument('--password', default='flowcore_secret')
parser.add_argument('--file',     default='generators/output/neo4j_seed.cypher')
parser.add_argument('--batch',    type=int, default=500,
                    help='Statements per transaction batch')
args = parser.parse_args()

if not os.path.exists(args.file):
    print(f"ERROR: {args.file} not found. Run generate_all.py first.")
    sys.exit(1)

# ── Try neo4j Python driver first ────────────────────────────────────────────
try:
    from neo4j import GraphDatabase, exceptions as neo4j_exc

    print(f"Connecting to Neo4j at {args.uri} ...")
    driver = GraphDatabase.driver(args.uri,
                                  auth=(args.user, args.password))

    # Wait for Neo4j to be ready
    for attempt in range(30):
        try:
            driver.verify_connectivity()
            print("  Neo4j connected.")
            break
        except Exception as e:
            print(f"  Waiting for Neo4j... ({attempt+1}/30): {e}")
            time.sleep(3)
    else:
        print("ERROR: Neo4j did not become available within 90s")
        sys.exit(1)

    # Parse statements from Cypher file
    # Statements are separated by semicolons (or blank-line groups for MERGE blocks)
    def parse_statements(filepath):
        """Parse Cypher file into individual statements."""
        stmts = []
        current = []
        with open(filepath, 'r') as f:
            for line in f:
                stripped = line.strip()
                # Skip comment-only lines and source directives
                if stripped.startswith('//') or stripped.startswith(':source'):
                    continue
                if stripped.endswith(';'):
                    current.append(stripped[:-1])  # remove trailing ;
                    stmt = ' '.join(current).strip()
                    if stmt:
                        stmts.append(stmt)
                    current = []
                else:
                    if stripped:
                        current.append(stripped)
        return stmts

    print(f"Parsing {args.file} ...")
    statements = parse_statements(args.file)
    print(f"  {len(statements)} Cypher statements to execute")

    # Execute in batches
    total_ok = 0
    total_err = 0
    batch_size = args.batch

    def run_batch(session, batch):
        for stmt in batch:
            try:
                session.run(stmt)
            except Exception as e:
                print(f"  WARN: {str(e)[:120]}")
                return False
        return True

    print(f"Loading in batches of {batch_size}...")
    start = time.time()

    with driver.session(database='neo4j') as session:
        for i in range(0, len(statements), batch_size):
            batch = statements[i:i+batch_size]
            with session.begin_transaction() as tx:
                for stmt in batch:
                    try:
                        tx.run(stmt)
                        total_ok += 1
                    except Exception as e:
                        total_err += 1
                        if total_err < 5:
                            print(f"  WARN stmt error: {str(e)[:100]}")
                tx.commit()

            pct = min(100, int((i + batch_size) / len(statements) * 100))
            elapsed = time.time() - start
            print(f"  [{pct:3d}%] {total_ok} ok, {total_err} errors — {elapsed:.1f}s elapsed")

    driver.close()
    elapsed = time.time() - start
    print(f"\n✓ Neo4j load complete: {total_ok} statements in {elapsed:.1f}s ({total_err} errors)")

except ImportError:
    # ── Fallback: cypher-shell ────────────────────────────────────────────────
    print("neo4j Python driver not found. Trying cypher-shell fallback...")
    result = subprocess.run(
        ['cypher-shell',
         '-a', args.uri,
         '-u', args.user,
         '-p', args.password,
         '--file', args.file],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✓ cypher-shell load complete")
    else:
        print(f"ERROR (cypher-shell):\n{result.stderr}")
        print("Install the neo4j Python driver: pip install neo4j")
        sys.exit(1)
