#!/usr/bin/env python3
"""
CSU Chico Website Scraper - FAST VERSION
- 0.5s delay per worker
- 4 parallel workers
- Graceful shutdown with Ctrl+C
- Better progress tracking
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import networkx as nx
import time
from collections import deque, defaultdict
import sys
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from datetime import datetime, timedelta


class CSUChicoScraperFast:
    def __init__(self, start_url="https://www.csuchico.edu", max_depth=6, delay=0.5, workers=4):
        self.start_url = start_url
        self.max_depth = max_depth
        self.delay = delay
        self.workers = workers

        # Graph structure
        self.graph = nx.DiGraph()
        self.graph_lock = threading.Lock()

        # Tracking
        self.visited_urls = set()
        self.visited_lock = threading.Lock()
        self.url_to_label = {}
        self.nav_footer_links = set()

        # Statistics
        self.stats_by_depth = defaultdict(lambda: {"pages": 0, "links": 0})
        self.stats_lock = threading.Lock()
        self.total_pages_scraped = 0
        self.start_time = None

        # Shutdown handling
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle Ctrl+C gracefully"""
        if not self.shutdown_requested:
            print("\n\n⚠️  INTERRUPT DETECTED - Saving progress...")
            print("Please wait while we save the graph...")
            self.shutdown_requested = True

    def is_valid_csuchico_url(self, url):
        """Check if URL is a valid CSU Chico page"""
        parsed = urlparse(url)

        if not parsed.netloc.endswith('csuchico.edu'):
            return False

        if parsed.netloc not in ['www.csuchico.edu', 'csuchico.edu']:
            return False

        skip_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip',
                          '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                          '.mp4', '.mp3', '.avi', '.mov', '.css', '.js')
        if any(parsed.path.lower().endswith(ext) for ext in skip_extensions):
            return False

        if parsed.scheme in ['mailto', 'tel']:
            return False

        return True

    def normalize_url(self, url):
        """Normalize URL by removing fragments and trailing slashes"""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized.endswith('/') and len(parsed.path) > 1:
            normalized = normalized[:-1]
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized

    def get_page_title(self, soup, url):
        """Extract a meaningful title from the page"""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            title = title.replace(' | CSU Chico', '')
            title = title.replace(' - CSU Chico', '')
            title = title.replace('CSU, Chico - ', '')
            return title[:100]

        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()[:100]

        path = urlparse(url).path
        if path and path != '/':
            return path.strip('/').replace('/', ' > ')[:100]

        return "CSU Chico Home"

    def extract_links(self, soup, base_url, is_homepage=False):
        """Extract all valid links from the page"""
        links = []

        if is_homepage:
            nav_elements = soup.find_all(['nav', 'header', 'footer'])
            for element in nav_elements:
                for a_tag in element.find_all('a', href=True):
                    href = a_tag['href']
                    full_url = urljoin(base_url, href)
                    normalized = self.normalize_url(full_url)
                    if self.is_valid_csuchico_url(normalized):
                        self.nav_footer_links.add(normalized)

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            normalized = self.normalize_url(full_url)

            if not self.is_valid_csuchico_url(normalized):
                continue

            link_text = a_tag.get_text().strip()
            if not link_text:
                link_text = a_tag.get('title', '')

            links.append((normalized, link_text))

        return links

    def fetch_page(self, url):
        """Fetch and parse a page"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Educational Research Project)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            response.raise_for_status()

            if not self.is_valid_csuchico_url(response.url):
                return None, None

            soup = BeautifulSoup(response.content, 'html.parser')
            return soup, response.url

        except Exception as e:
            print(f"  ✗ Error: {url[:60]} - {str(e)[:50]}", file=sys.stderr)
            return None, None

    def process_page(self, current_url, depth, parent_url):
        """Process a single page (thread-safe)"""
        if self.shutdown_requested:
            return []

        soup, final_url = self.fetch_page(current_url)
        if soup is None:
            return []

        # Update URL if redirected
        if final_url and final_url != current_url:
            current_url = self.normalize_url(final_url)
            with self.visited_lock:
                if current_url in self.visited_urls:
                    return []
                self.visited_urls.add(current_url)

        # Get page title
        title = self.get_page_title(soup, current_url)

        with self.graph_lock:
            self.url_to_label[current_url] = title
            self.graph.add_node(current_url, label=title, depth=depth)
            if parent_url:
                self.graph.add_edge(parent_url, current_url)

        # Extract links
        is_homepage = (depth == 0)
        links = self.extract_links(soup, current_url, is_homepage)

        # Filter links if not homepage
        if not is_homepage:
            links = [(url, text) for url, text in links
                    if url not in self.nav_footer_links or url not in self.visited_urls]

        # Prepare new links for queue
        new_links = []
        with self.visited_lock:
            for link_url, link_text in links:
                if link_url not in self.visited_urls:
                    self.visited_urls.add(link_url)
                    new_links.append((link_url, link_text, depth + 1))

                    if link_url not in self.url_to_label and link_text:
                        self.url_to_label[link_url] = link_text[:100]
                else:
                    # Still add edge even if already visited
                    with self.graph_lock:
                        if link_url in self.graph:
                            self.graph.add_edge(current_url, link_url)

        # Update stats
        with self.stats_lock:
            self.stats_by_depth[depth]["pages"] += 1
            self.stats_by_depth[depth]["links"] += len(new_links)
            self.total_pages_scraped += 1

        return new_links

    def print_progress(self, depth, queue_size):
        """Print progress with time estimate"""
        with self.stats_lock:
            stats = self.stats_by_depth[depth]
            elapsed = time.time() - self.start_time

            # Estimate time remaining
            if self.total_pages_scraped > 0:
                avg_time_per_page = elapsed / self.total_pages_scraped
                est_remaining = avg_time_per_page * queue_size / self.workers
                est_finish = datetime.now() + timedelta(seconds=est_remaining)

                print(f"\r📊 D{depth}: {stats['pages']} pages | "
                      f"{stats['links']} links | "
                      f"Queue: {queue_size} | "
                      f"Total: {self.total_pages_scraped} | "
                      f"ETA: {est_finish.strftime('%H:%M:%S')}",
                      end='', flush=True)

    def scrape(self):
        """Main scraping function using parallel BFS"""
        print(f"🚀 Starting FAST scrape of {self.start_url}")
        print(f"⚙️  Config: {self.workers} workers, {self.delay}s delay, depth {self.max_depth}")
        print(f"⚠️  Press Ctrl+C to stop and save progress")
        print("=" * 80)

        self.start_time = time.time()

        # Initialize with homepage
        with self.visited_lock:
            self.visited_urls.add(self.start_url)

        queue = deque([(self.start_url, 0, None)])
        current_depth = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            while queue and not self.shutdown_requested:
                # Check if we've moved to a new depth
                if queue and queue[0][1] != current_depth:
                    current_depth = queue[0][1]
                    print(f"\n\n{'='*80}")
                    print(f"📍 Starting Depth {current_depth}")
                    print(f"{'='*80}")

                if current_depth > self.max_depth:
                    break

                # Batch processing for current depth
                batch_size = min(self.workers * 10, len(queue))
                futures = {}

                for _ in range(batch_size):
                    if not queue or self.shutdown_requested:
                        break

                    current_url, depth, parent_url = queue.popleft()

                    if depth > self.max_depth:
                        continue

                    future = executor.submit(self.process_page, current_url, depth, parent_url)
                    futures[future] = (current_url, depth)
                    time.sleep(self.delay / self.workers)  # Stagger starts

                # Collect results
                for future in as_completed(futures):
                    if self.shutdown_requested:
                        break

                    new_links = future.result()
                    for link_url, link_text, depth in new_links:
                        queue.append((link_url, depth, futures[future][0]))

                    # Update progress display
                    if self.total_pages_scraped % 5 == 0:
                        self.print_progress(futures[future][1], len(queue))

        print("\n\n" + "=" * 80)
        if self.shutdown_requested:
            print("⚠️  SCRAPING INTERRUPTED")
        else:
            print("✅ SCRAPING COMPLETE")
        self.print_final_summary()

    def print_final_summary(self):
        """Print final statistics"""
        elapsed = time.time() - self.start_time
        print(f"\n📊 Final Statistics:")
        print(f"  Total nodes: {self.graph.number_of_nodes()}")
        print(f"  Total edges: {self.graph.number_of_edges()}")
        print(f"  Nav/footer links: {len(self.nav_footer_links)}")
        print(f"  Time elapsed: {elapsed/60:.1f} minutes")
        print(f"  Avg speed: {self.total_pages_scraped/elapsed:.2f} pages/sec")
        print(f"\n📈 Breakdown by depth:")
        for depth in sorted(self.stats_by_depth.keys()):
            stats = self.stats_by_depth[depth]
            print(f"    Depth {depth}: {stats['pages']:4d} pages, {stats['links']:4d} links")

    def get_graph(self):
        """Return the constructed graph"""
        return self.graph

    def save_as_python_file(self, output_file="csuchico_graph.py"):
        """Save graph as a Python file that can be imported"""
        print(f"\n💾 Saving graph to {output_file}...")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write('CSU Chico Website Graph\n')
            f.write(f'Scraped from {self.start_url}\n')
            f.write(f'Nodes: {self.graph.number_of_nodes()}\n')
            f.write(f'Edges: {self.graph.number_of_edges()}\n')
            if self.shutdown_requested:
                f.write('WARNING: Scraping was interrupted - this is a partial graph\n')
            f.write('"""\n\n')
            f.write('import networkx as nx\n\n')
            f.write('def create_csuchico_graph():\n')
            f.write('    """Create and return the CSU Chico website graph"""\n')
            f.write('    G = nx.DiGraph()\n\n')

            # Add nodes with labels
            f.write('    # Add nodes with labels\n')
            f.write('    nodes = [\n')
            for node in self.graph.nodes():
                label = self.url_to_label.get(node, node)
                label = label.replace("'", "\\'").replace("\n", " ")
                f.write(f"        ('{node}', '{label}'),\n")
            f.write('    ]\n')
            f.write('    for url, label in nodes:\n')
            f.write('        G.add_node(url, label=label)\n\n')

            # Add edges
            f.write('    # Add edges\n')
            f.write('    edges = [\n')
            for source, target in self.graph.edges():
                f.write(f"        ('{source}', '{target}'),\n")
            f.write('    ]\n')
            f.write('    G.add_edges_from(edges)\n\n')
            f.write('    return G\n\n')

            # Add main block for testing
            f.write('if __name__ == "__main__":\n')
            f.write('    G = create_csuchico_graph()\n')
            f.write('    print(f"Loaded graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")\n')
            f.write('    print(f"\\nSample nodes:")\n')
            f.write('    for i, (node, data) in enumerate(G.nodes(data=True)):\n')
            f.write('        if i < 10:\n')
            f.write('            print(f"  {data.get(\'label\', node)[:60]}")\n')

        print(f"✅ Saved graph to {output_file}")


def main():
    scraper = CSUChicoScraperFast(
        start_url="https://www.csuchico.edu",
        max_depth=6,
        delay=0.5,
        workers=4
    )

    try:
        scraper.scrape()
    finally:
        # Always save, even if interrupted
        scraper.save_as_python_file("csuchico_graph.py")
        print("\n✅ Done! Import the graph with:")
        print("  from csuchico_graph import create_csuchico_graph")
        print("  G = create_csuchico_graph()")


if __name__ == "__main__":
    main()