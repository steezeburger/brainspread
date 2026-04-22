// GraphView - force-directed canvas visualization of pages and their links.
const GraphView = {
  data() {
    return {
      loading: true,
      error: null,
      nodes: [],
      edges: [],
      adjacency: new Map(),
      includeDaily: false,
      includeOrphans: true,
      hoveredNode: null,
      draggingNode: null,
      dragOffset: { x: 0, y: 0 },
      dragStartClient: { x: 0, y: 0 },
      dragMoved: false,
      panOffset: { x: 0, y: 0 },
      zoom: 1,
      isPanning: false,
      panStart: { x: 0, y: 0 },
      panOffsetStart: { x: 0, y: 0 },
      width: 800,
      height: 600,
      animationFrame: null,
      simulationAlpha: 1,
      resizeObserver: null,
      devicePixelRatio: window.devicePixelRatio || 1,
      // Physics params
      repulsionStrength: 1800,
      linkDistance: 90,
      linkStrength: 0.05,
      centerStrength: 0.02,
      friction: 0.85,
    };
  },

  computed: {
    nodeCount() {
      return this.nodes.length;
    },
    edgeCount() {
      return this.edges.length;
    },
    statusMessage() {
      if (this.loading) return "loading graph...";
      if (this.error) return `error: ${this.error}`;
      if (!this.nodes.length) {
        return "no pages to display - create some pages and link them with [[wikilinks]] or #hashtags";
      }
      return `${this.nodeCount} pages · ${this.edgeCount} connections`;
    },
  },

  async mounted() {
    await this.loadGraph();
    this.setupCanvas();
    this.setupResizeObserver();
    this.startSimulation();
    window.addEventListener("keydown", this.handleKeydown);
  },

  beforeUnmount() {
    this.stopSimulation();
    window.removeEventListener("keydown", this.handleKeydown);
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
  },

  methods: {
    async loadGraph() {
      this.loading = true;
      this.error = null;
      try {
        const result = await window.apiService.getGraphData({
          includeDaily: this.includeDaily,
          includeOrphans: this.includeOrphans,
        });
        if (!result.success) {
          this.error =
            result.errors?.non_field_errors?.[0] || "failed to load graph";
          this.nodes = [];
          this.edges = [];
          return;
        }
        this.initializeSimulation(result.data.nodes, result.data.edges);
      } catch (err) {
        console.error("Failed to load graph:", err);
        this.error = err.message || "failed to load graph";
        this.nodes = [];
        this.edges = [];
      } finally {
        this.loading = false;
      }
    },

    initializeSimulation(rawNodes, rawEdges) {
      const cx = this.width / 2;
      const cy = this.height / 2;
      const radius = Math.min(this.width, this.height) * 0.35;
      const markRaw = (Vue && Vue.markRaw) || ((v) => v);

      const nodes = rawNodes.map((n, i) => {
        const angle = (i / Math.max(rawNodes.length, 1)) * Math.PI * 2;
        return markRaw({
          ...n,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
          vx: 0,
          vy: 0,
        });
      });

      const byUuid = new Map(nodes.map((n) => [n.uuid, n]));
      const edges = rawEdges
        .map((e) =>
          markRaw({
            source: byUuid.get(e.source),
            target: byUuid.get(e.target),
            weight: e.weight || 1,
          })
        )
        .filter((e) => e.source && e.target);

      this.nodes = markRaw(nodes);
      this.edges = markRaw(edges);

      const adj = new Map();
      for (const node of this.nodes) adj.set(node.uuid, new Set());
      for (const edge of this.edges) {
        adj.get(edge.source.uuid).add(edge.target.uuid);
        adj.get(edge.target.uuid).add(edge.source.uuid);
      }
      this.adjacency = adj;

      this.simulationAlpha = 1;
    },

    setupCanvas() {
      const canvas = this.$refs.canvas;
      if (!canvas) return;
      const container = this.$refs.container;
      if (container) {
        const rect = container.getBoundingClientRect();
        this.width = Math.max(300, rect.width);
        this.height = Math.max(300, rect.height);
      }
      this.resizeCanvas();
    },

    resizeCanvas() {
      const canvas = this.$refs.canvas;
      if (!canvas) return;
      const dpr = this.devicePixelRatio;
      canvas.width = this.width * dpr;
      canvas.height = this.height * dpr;
      canvas.style.width = `${this.width}px`;
      canvas.style.height = `${this.height}px`;
    },

    setupResizeObserver() {
      if (typeof ResizeObserver === "undefined") return;
      const container = this.$refs.container;
      if (!container) return;
      this.resizeObserver = new ResizeObserver(() => {
        const rect = container.getBoundingClientRect();
        this.width = Math.max(300, rect.width);
        this.height = Math.max(300, rect.height);
        this.resizeCanvas();
        this.render();
      });
      this.resizeObserver.observe(container);
    },

    startSimulation() {
      const step = () => {
        this.tick();
        this.render();
        this.animationFrame = requestAnimationFrame(step);
      };
      this.animationFrame = requestAnimationFrame(step);
    },

    stopSimulation() {
      if (this.animationFrame) {
        cancelAnimationFrame(this.animationFrame);
        this.animationFrame = null;
      }
    },

    tick() {
      if (!this.nodes.length) return;

      const alpha = Math.max(this.simulationAlpha, 0.02);

      // Repulsion between all node pairs (O(n^2) - fine for the sizes we expect)
      for (let i = 0; i < this.nodes.length; i++) {
        const a = this.nodes[i];
        if (a === this.draggingNode) continue;
        for (let j = i + 1; j < this.nodes.length; j++) {
          const b = this.nodes[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let distSq = dx * dx + dy * dy;
          if (distSq < 0.01) {
            dx = Math.random() - 0.5;
            dy = Math.random() - 0.5;
            distSq = dx * dx + dy * dy + 0.01;
          }
          const dist = Math.sqrt(distSq);
          const force = (this.repulsionStrength * alpha) / distSq;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx += fx;
          a.vy += fy;
          if (b !== this.draggingNode) {
            b.vx -= fx;
            b.vy -= fy;
          }
        }
      }

      // Spring attraction along edges
      for (const edge of this.edges) {
        const { source, target } = edge;
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const diff = dist - this.linkDistance;
        const force = diff * this.linkStrength * alpha * edge.weight;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        if (source !== this.draggingNode) {
          source.vx += fx;
          source.vy += fy;
        }
        if (target !== this.draggingNode) {
          target.vx -= fx;
          target.vy -= fy;
        }
      }

      // Weak centering force
      const cx = this.width / 2;
      const cy = this.height / 2;
      for (const node of this.nodes) {
        if (node === this.draggingNode) continue;
        node.vx += (cx - node.x) * this.centerStrength * alpha;
        node.vy += (cy - node.y) * this.centerStrength * alpha;
      }

      // Apply velocities with friction
      for (const node of this.nodes) {
        if (node === this.draggingNode) {
          node.vx = 0;
          node.vy = 0;
          continue;
        }
        node.vx *= this.friction;
        node.vy *= this.friction;
        // Clamp velocity so the simulation stays stable
        const maxV = 30;
        if (node.vx > maxV) node.vx = maxV;
        if (node.vx < -maxV) node.vx = -maxV;
        if (node.vy > maxV) node.vy = maxV;
        if (node.vy < -maxV) node.vy = -maxV;
        node.x += node.vx;
        node.y += node.vy;
      }

      this.simulationAlpha *= 0.995;
    },

    nodeRadius(node) {
      return 4 + Math.min(12, Math.sqrt(node.block_count + node.degree));
    },

    nodeColor(node) {
      const styles = getComputedStyle(document.documentElement);
      if (node.page_type === "daily") {
        return styles.getPropertyValue("--text-muted").trim() || "#888";
      }
      if (node.page_type === "whiteboard") {
        return styles.getPropertyValue("--context-color").trim() || "#ffaa00";
      }
      return styles.getPropertyValue("--text-primary").trim() || "#00ff00";
    },

    render() {
      const canvas = this.$refs.canvas;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const dpr = this.devicePixelRatio;

      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.scale(dpr, dpr);

      ctx.translate(this.panOffset.x, this.panOffset.y);
      ctx.scale(this.zoom, this.zoom);

      const styles = getComputedStyle(document.documentElement);
      const edgeColor =
        styles.getPropertyValue("--border-secondary").trim() || "#333";
      const edgeHighlight =
        styles.getPropertyValue("--border-primary").trim() || "#00ff00";
      const textColor =
        styles.getPropertyValue("--text-primary").trim() || "#00ff00";
      const bgColor = styles.getPropertyValue("--bg-primary").trim() || "#000";

      const hoveredUuid = this.hoveredNode?.uuid || null;
      const neighborUuids = hoveredUuid
        ? this.adjacency.get(hoveredUuid) || new Set()
        : new Set();

      // Edges
      ctx.lineWidth = 1;
      for (const edge of this.edges) {
        const touchesHovered =
          hoveredUuid &&
          (edge.source.uuid === hoveredUuid ||
            edge.target.uuid === hoveredUuid);
        ctx.strokeStyle = touchesHovered ? edgeHighlight : edgeColor;
        ctx.globalAlpha = hoveredUuid && !touchesHovered ? 0.2 : 0.7;
        ctx.lineWidth = touchesHovered ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(edge.source.x, edge.source.y);
        ctx.lineTo(edge.target.x, edge.target.y);
        ctx.stroke();
      }

      // Nodes
      ctx.globalAlpha = 1;
      for (const node of this.nodes) {
        const radius = this.nodeRadius(node);
        const color = this.nodeColor(node);
        const isHovered = hoveredUuid === node.uuid;
        const isNeighbor = neighborUuids.has(node.uuid);
        const dimmed = hoveredUuid && !isHovered && !isNeighbor;

        ctx.globalAlpha = dimmed ? 0.3 : 1;
        ctx.fillStyle = color;
        ctx.strokeStyle = bgColor;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        if (isHovered || (!hoveredUuid && radius >= 8) || isNeighbor) {
          ctx.globalAlpha = dimmed ? 0.3 : 1;
          ctx.fillStyle = textColor;
          ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, monospace";
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(node.title, node.x + radius + 6, node.y);
        }
      }

      ctx.globalAlpha = 1;
      ctx.restore();
    },

    toGraphCoords(clientX, clientY) {
      const canvas = this.$refs.canvas;
      const rect = canvas.getBoundingClientRect();
      const localX = clientX - rect.left;
      const localY = clientY - rect.top;
      return {
        x: (localX - this.panOffset.x) / this.zoom,
        y: (localY - this.panOffset.y) / this.zoom,
      };
    },

    pickNode(graphX, graphY) {
      // Iterate in reverse so top-rendered nodes are picked first
      for (let i = this.nodes.length - 1; i >= 0; i--) {
        const node = this.nodes[i];
        const dx = graphX - node.x;
        const dy = graphY - node.y;
        const r = this.nodeRadius(node) + 3;
        if (dx * dx + dy * dy <= r * r) return node;
      }
      return null;
    },

    onMouseDown(event) {
      const { x, y } = this.toGraphCoords(event.clientX, event.clientY);
      const node = this.pickNode(x, y);
      if (node) {
        this.draggingNode = node;
        this.dragOffset = { x: x - node.x, y: y - node.y };
        this.dragStartClient = { x: event.clientX, y: event.clientY };
        this.dragMoved = false;
        this.simulationAlpha = Math.max(this.simulationAlpha, 0.5);
      } else {
        this.isPanning = true;
        this.panStart = { x: event.clientX, y: event.clientY };
        this.panOffsetStart = { ...this.panOffset };
      }
    },

    onMouseMove(event) {
      if (this.draggingNode) {
        const dx = event.clientX - this.dragStartClient.x;
        const dy = event.clientY - this.dragStartClient.y;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          this.dragMoved = true;
        }
        const { x, y } = this.toGraphCoords(event.clientX, event.clientY);
        this.draggingNode.x = x - this.dragOffset.x;
        this.draggingNode.y = y - this.dragOffset.y;
        this.draggingNode.vx = 0;
        this.draggingNode.vy = 0;
        return;
      }

      if (this.isPanning) {
        this.panOffset.x =
          this.panOffsetStart.x + (event.clientX - this.panStart.x);
        this.panOffset.y =
          this.panOffsetStart.y + (event.clientY - this.panStart.y);
        return;
      }

      const { x, y } = this.toGraphCoords(event.clientX, event.clientY);
      this.hoveredNode = this.pickNode(x, y);
      const canvas = this.$refs.canvas;
      if (canvas) {
        canvas.style.cursor = this.hoveredNode ? "pointer" : "grab";
      }
    },

    onMouseUp() {
      if (this.draggingNode && !this.dragMoved) {
        this.navigateToNode(this.draggingNode);
      }
      this.draggingNode = null;
      this.dragMoved = false;
      this.isPanning = false;
    },

    onMouseLeave() {
      this.draggingNode = null;
      this.isPanning = false;
      this.hoveredNode = null;
    },

    onWheel(event) {
      event.preventDefault();
      const canvas = this.$refs.canvas;
      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const delta = -event.deltaY * 0.001;
      const nextZoom = Math.max(0.2, Math.min(4, this.zoom * (1 + delta)));
      // Zoom to cursor
      const graphBefore = {
        x: (mouseX - this.panOffset.x) / this.zoom,
        y: (mouseY - this.panOffset.y) / this.zoom,
      };
      this.zoom = nextZoom;
      this.panOffset.x = mouseX - graphBefore.x * this.zoom;
      this.panOffset.y = mouseY - graphBefore.y * this.zoom;
    },

    navigateToNode(node) {
      if (!node || !node.slug) return;
      window.location.href = `/knowledge/page/${node.slug}/`;
    },

    resetView() {
      this.zoom = 1;
      this.panOffset = { x: 0, y: 0 };
      this.simulationAlpha = 1;
    },

    async refresh() {
      this.simulationAlpha = 1;
      await this.loadGraph();
    },

    async onToggleDaily() {
      this.includeDaily = !this.includeDaily;
      await this.refresh();
    },

    async onToggleOrphans() {
      this.includeOrphans = !this.includeOrphans;
      await this.refresh();
    },

    handleKeydown(event) {
      if (event.key === "Escape") {
        window.location.href = "/knowledge/";
      } else if (event.key === "r" && !event.metaKey && !event.ctrlKey) {
        const target = event.target;
        if (
          target &&
          (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
        ) {
          return;
        }
        this.resetView();
      }
    },
  },

  template: `
    <div class="graph-view">
      <div class="graph-toolbar">
        <div class="graph-toolbar-left">
          <span class="graph-status">{{ statusMessage }}</span>
        </div>
        <div class="graph-toolbar-right">
          <label class="graph-toggle">
            <input type="checkbox" :checked="includeDaily" @change="onToggleDaily" />
            daily notes
          </label>
          <label class="graph-toggle">
            <input type="checkbox" :checked="includeOrphans" @change="onToggleOrphans" />
            orphans
          </label>
          <button class="graph-btn" @click="resetView" title="reset zoom/pan (r)">reset</button>
          <button class="graph-btn" @click="refresh" title="reload graph">reload</button>
        </div>
      </div>
      <div class="graph-canvas-container" ref="container">
        <canvas
          ref="canvas"
          class="graph-canvas"
          @mousedown="onMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseLeave"
          @wheel="onWheel"
        ></canvas>
        <div v-if="loading" class="graph-overlay">loading graph...</div>
        <div v-else-if="error" class="graph-overlay graph-overlay-error">{{ error }}</div>
        <div v-else-if="!nodeCount" class="graph-overlay">
          no pages to display yet - create pages and link them with [[wikilinks]] or #hashtags
        </div>
      </div>
      <div class="graph-help">
        drag nodes to reposition · scroll to zoom · click a node to open · press r to reset · esc to exit
      </div>
    </div>
  `,
};

window.GraphView = GraphView;
