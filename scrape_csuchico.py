#!/usr/bin/env python3
"""
CSU Chico Website Scraper
Builds a directed graph of the CSU Chico website structure
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import networkx as nx
import time
from collections import deque, defaultdict
import sys


class CSUChicoScraper:
    def __init__(self, start_url="https://www.csuchico.edu", max_depth=6, delay=2.0):
        self.start_url = start_url
        self.max_depth = max_depth
        self.delay = delay

        # Graph structure
        self.graph = nx.DiGraph()

        # Tracking
        self.visited_urls = set()
        self.url_to_label = {}  # Maps URLs to their display labels
        self.nav_footer_links = set()  # Links that appear in nav/footer from homepage

        # Statistics
        self.stats_by_depth = defaultdict(lambda: {"pages": 0, "links": 0})

    def is_valid_csuchico_url(self, url):
        """Check if URL is a valid CSU Chico page"""
        parsed = urlparse(url)

        # Must be csuchico.edu domain
        if not parsed.netloc.endswith('csuchico.edu'):
            return False

        # Must be www subdomain or base domain
        if parsed.netloc not in ['www.csuchico.edu', 'csuchico.edu']:
            return False

        # Skip non-HTML resources
        skip_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip',
                          '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                          '.mp4', '.mp3', '.avi', '.mov', '.css', '.js')
        if any(parsed.path.lower().endswith(ext) for ext in skip_extensions):
            return False

        # Skip mailto and tel links
        if parsed.scheme in ['mailto', 'tel']:
            return False

        return True

    def normalize_url(self, url):
        """Normalize URL by removing fragments and trailing slashes"""
        parsed = urlparse(url)
        # Remove fragment, normalize trailing slash
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized.endswith('/') and len(parsed.path) > 1:
            normalized = normalized[:-1]
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized

    def get_page_title(self, soup, url):
        """Extract a meaningful title from the page"""
        # Try <title> tag first
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            # Clean up common patterns
            title = title.replace(' | CSU Chico', '')
            title = title.replace(' - CSU Chico', '')
            title = title.replace('CSU, Chico - ', '')
            return title[:100]  # Limit length

        # Try <h1> tag
        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()[:100]

        # Fall back to URL path
        path = urlparse(url).path
        if path and path != '/':
            return path.strip('/').replace('/', ' > ')[:100]

        return "CSU Chico Home"

    def extract_links(self, soup, base_url, is_homepage=False):
        """Extract all valid links from the page"""
        links = []

        # If this is the homepage, identify nav/footer links
        if is_homepage:
            # Find navigation and footer elements
            nav_elements = soup.find_all(['nav', 'header', 'footer'])
            for element in nav_elements:
                for a_tag in element.find_all('a', href=True):
                    href = a_tag['href']
                    full_url = urljoin(base_url, href)
                    normalized = self.normalize_url(full_url)
                    if self.is_valid_csuchico_url(normalized):
                        self.nav_footer_links.add(normalized)

        # Extract all links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            normalized = self.normalize_url(full_url)

            if not self.is_valid_csuchico_url(normalized):
                continue

            # Get link text for label (first occurrence wins)
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

            # Check if we got redirected to a different domain
            if not self.is_valid_csuchico_url(response.url):
                return None, []

            soup = BeautifulSoup(response.content, 'html.parser')
            return soup, response.url  # Return actual URL after redirects

        except Exception as e:
            print(f"  ✗ Error fetching {url}: {str(e)[:100]}", file=sys.stderr)
            return None, None

    def scrape(self):
        """Main scraping function using BFS"""
        print(f"Starting scrape of {self.start_url}")
        print(f"Max depth: {self.max_depth}, Delay: {self.delay}s")
        print("=" * 80)

        # BFS queue: (url, depth, parent_url)
        queue = deque([(self.start_url, 0, None)])
        self.visited_urls.add(self.start_url)

        while queue:
            current_url, depth, parent_url = queue.popleft()

            if depth > self.max_depth:
                continue

            print(f"\n[Depth {depth}] Fetching: {current_url}")

            # Fetch page
            soup, final_url = self.fetch_page(current_url)
            if soup is None:
                continue

            # Update URL if redirected
            if final_url and final_url != current_url:
                current_url = self.normalize_url(final_url)
                if current_url in self.visited_urls:
                    print(f"  ↪ Redirected to already-visited page")
                    continue
                self.visited_urls.add(current_url)

            # Get page title
            title = self.get_page_title(soup, current_url)
            self.url_to_label[current_url] = title

            # Add node to graph
            self.graph.add_node(current_url, label=title, depth=depth)

            # Add edge from parent
            if parent_url:
                self.graph.add_edge(parent_url, current_url)

            # Extract links
            is_homepage = (depth == 0)
            links = self.extract_links(soup, current_url, is_homepage)

            # Filter links if not homepage
            if not is_homepage:
                # Skip nav/footer links that we already crawled from homepage
                links = [(url, text) for url, text in links
                        if url not in self.nav_footer_links or url not in self.visited_urls]

            print(f"  ✓ Found {len(links)} links, Title: '{title[:60]}'")

            # Add links to queue
            new_links_added = 0
            for link_url, link_text in links:
                if link_url not in self.visited_urls:
                    self.visited_urls.add(link_url)
                    queue.append((link_url, depth + 1, current_url))
                    new_links_added += 1

                    # Store label from first occurrence
                    if link_url not in self.url_to_label and link_text:
                        self.url_to_label[link_url] = link_text[:100]
                else:
                    # Still add edge even if already visited
                    if link_url in self.graph:
                        self.graph.add_edge(current_url, link_url)

            # Update stats
            self.stats_by_depth[depth]["pages"] += 1
            self.stats_by_depth[depth]["links"] += new_links_added

            # Print depth summary periodically
            if self.stats_by_depth[depth]["pages"] % 10 == 0 or queue[0][1] != depth if queue else True:
                self.print_depth_summary(depth)

            # Rate limiting
            time.sleep(self.delay)

        print("\n" + "=" * 80)
        print("SCRAPING COMPLETE")
        self.print_final_summary()

    def print_depth_summary(self, depth):
        """Print summary for a depth level"""
        stats = self.stats_by_depth[depth]
        print(f"  📊 Depth {depth} summary: {stats['pages']} pages, {stats['links']} new links found")

    def print_final_summary(self):
        """Print final statistics"""
        print(f"\nTotal nodes: {self.graph.number_of_nodes()}")
        print(f"Total edges: {self.graph.number_of_edges()}")
        print(f"Nav/footer links identified: {len(self.nav_footer_links)}")
        print("\nBreakdown by depth:")
        for depth in sorted(self.stats_by_depth.keys()):
            stats = self.stats_by_depth[depth]
            print(f"  Depth {depth}: {stats['pages']} pages, {stats['links']} links")

    def get_graph(self):
        """Return the constructed graph"""
        return self.graph

    def save_as_python_file(self, output_file="csuchico_graph.py"):
        """Save graph as a Python file that can be imported"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write('CSU Chico Website Graph\n')
            f.write(f'Scraped from {self.start_url}\n')
            f.write(f'Nodes: {self.graph.number_of_nodes()}\n')
            f.write(f'Edges: {self.graph.number_of_edges()}\n')
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
                # Escape quotes in label
                label = label.replace("'", "\\'")
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

        print(f"\n✓ Saved graph to {output_file}")


def main():
    scraper = CSUChicoScraper(
        start_url="https://www.csuchico.edu",
        max_depth=6,
        delay=2.0
    )

    scraper.scrape()
    scraper.save_as_python_file("csuchico_graph.py")

    print("\n✓ Done! Import the graph with:")
    print("  from csuchico_graph import create_csuchico_graph")
    print("  G = create_csuchico_graph()")


if __name__ == "__main__":
    main()