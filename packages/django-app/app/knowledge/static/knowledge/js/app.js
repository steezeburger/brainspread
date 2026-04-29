const { createApp } = Vue;

const AVAILABLE_THEMES = [
  { id: "dark", label: "dark" },
  { id: "light", label: "light" },
  { id: "solarized_dark", label: "solarized dark" },
  { id: "purple", label: "purple" },
  { id: "earthy", label: "earthy" },
  { id: "forest", label: "forest" },
];

// Global Vue app for knowledge base
const KnowledgeApp = createApp({
  data() {
    const isAuth = window.apiService.isAuthenticated();
    const cachedUser = window.apiService.getCurrentUser();

    const isGraphRoute = window.location.pathname === "/knowledge/graph/";
    const initialView = isAuth ? (isGraphRoute ? "graph" : "journal") : "login";

    return {
      user: cachedUser, // Load user immediately from cache
      isAuthenticated: isAuth, // Check immediately
      currentView: initialView, // Set view immediately
      loading: isAuth && !cachedUser, // Only show loading if we have token but no cached user
      showSettings: false, // Settings modal state
      settingsActiveTab: "general", // Default tab for settings modal
      showHelp: false, // Help modal state
      // Chat context management
      chatContextBlocks: [], // Array of blocks in chat context
      visibleBlocks: [], // Array of currently visible blocks
      // Toast notifications
      toasts: [], // Array of toast notifications
      toastIdCounter: 0, // Counter for unique toast IDs
      // Spotlight search
      showSpotlight: false, // Spotlight search modal state
      spotlightQuery: "", // Current search query
      spotlightResults: [], // Search results
      spotlightLoading: false, // Loading state for search
      spotlightSelectedIndex: 0, // Selected result index for keyboard navigation
      spotlightSearchTimeout: null, // Debounce timeout for search
      currentPagePageType: null, // page_type of the currently-loaded page
    };
  },

  components: {
    Page: window.Page,
    LoginForm: window.LoginForm,
    LeftNav: window.LeftNav,
    SettingsModal: window.SettingsModal,
    HelpModal: window.HelpModal,
    ChatPanel: window.ChatPanel,
    ToastNotifications: window.ToastNotifications,
    SpotlightSearch: window.SpotlightSearch,
    GraphView: window.GraphView,
  },

  computed: {
    currentPageType() {
      const path = window.location.pathname;

      // Extract page type from URL path
      const pathParts = path.split("/").filter((part) => part);

      if (pathParts.length >= 2 && pathParts[0] === "knowledge") {
        const pageType = pathParts[1];
        // Valid page types: tag, page
        if (["tag", "page"].includes(pageType)) {
          return pageType;
        }
      }

      return "page"; // Default fallback for /knowledge/ - redirect to today's date
    },

    showChatPanel() {
      // Whiteboards and the graph view use the full column width; chat is noise there.
      if (this.currentView === "graph") return false;
      return this.currentPagePageType !== "whiteboard";
    },
  },

  async mounted() {
    console.log("Knowledge app mounted");

    // Apply initial theme
    this.applyTheme();

    // Add global keyboard shortcut listener
    document.addEventListener("keydown", this.handleGlobalKeydown);

    // Toast bridge: child components dispatch 'brainspread:toast' with detail
    // { message, type, duration } rather than reaching into this component.
    document.addEventListener("brainspread:toast", this.handleToastEvent);

    // If we have cached user data, we can show the app immediately
    if (this.isAuthenticated && this.user) {
      this.loading = false;
    }

    // Then verify with server (this happens in background)
    await this.checkAuth();

    // Check for timezone changes after authentication
    if (this.isAuthenticated) {
      this.checkTimezoneChange();
    }

    // Redirect to today's page if we're on the root knowledge page
    if (this.isAuthenticated && window.location.pathname === "/knowledge/") {
      this.redirectToToday();
      return;
    }

    if (
      this.isAuthenticated &&
      window.location.pathname === "/knowledge/graph/"
    ) {
      this.currentView = "graph";
    }

    // Reapply theme after auth check in case user data was updated
    this.applyTheme();
  },

  beforeUnmount() {
    // Clean up event listeners
    document.removeEventListener("keydown", this.handleGlobalKeydown);
    document.removeEventListener("brainspread:toast", this.handleToastEvent);
  },

  methods: {
    async checkAuth() {
      // Only set loading if we're not already authenticated
      if (!this.isAuthenticated) {
        this.loading = true;
      }

      if (window.apiService.isAuthenticated()) {
        try {
          const result = await window.apiService.me();
          if (result.success) {
            this.user = result.data.user;
            this.isAuthenticated = true;
            this.currentView = "journal";
          } else {
            this.handleLogout();
          }
        } catch (error) {
          console.error("Auth check failed:", error);
          this.handleLogout();
        }
      } else {
        this.currentView = "login";
        this.isAuthenticated = false;
      }

      this.loading = false;
    },

    onLoginSuccess(user) {
      this.user = user;
      this.isAuthenticated = true;
      this.currentView = "journal";

      // Check timezone after login (with a small delay to ensure user data is updated)
      setTimeout(() => {
        this.checkTimezoneChange();
      }, 1000);
    },

    async handleLogout() {
      try {
        await window.apiService.logout();
      } catch (error) {
        console.error("Logout error:", error);
      } finally {
        this.user = null;
        this.isAuthenticated = false;
        this.currentView = "login";
      }
    },

    checkTimezoneChange() {
      if (window.apiService.checkTimezoneChange()) {
        const browserTimezone = window.apiService.getCurrentBrowserTimezone();
        const currentUser = window.apiService.getCurrentUser();

        const message = `Your device's timezone appears to have changed from ${currentUser.timezone} to ${browserTimezone}. Would you like to update your timezone preference?`;

        if (confirm(message)) {
          this.updateTimezone(browserTimezone);
        }
      }
    },

    async updateTimezone(newTimezone) {
      try {
        const result = await window.apiService.updateUserTimezone(newTimezone);
        if (result.success) {
          console.log("Timezone updated successfully");
          // Optionally reload the page to refresh with new timezone
          // window.location.reload();
        }
      } catch (error) {
        console.error("Failed to update timezone:", error);
        alert("Failed to update timezone. Please try again.");
      }
    },

    onNavigateToDate(date) {
      // Navigate to the unified page URL with date as slug
      window.location.href = `/knowledge/page/${date}/`;
    },
    onNavigateToSlug(slug) {
      window.location.href = `/knowledge/page/${slug}/`;
    },

    redirectToToday() {
      // Get today's date in YYYY-MM-DD format
      const today = new Date();
      const year = today.getFullYear();
      const month = String(today.getMonth() + 1).padStart(2, "0");
      const day = String(today.getDate()).padStart(2, "0");
      const todayString = `${year}-${month}-${day}`;

      // Redirect to today's page
      window.location.href = `/knowledge/page/${todayString}/`;
    },

    // Theme and settings methods
    openSettings(activeTab = "general") {
      this.settingsActiveTab = activeTab;
      this.showSettings = true;
    },

    closeSettings() {
      this.showSettings = false;
      this.settingsActiveTab = "general"; // Reset to default
    },

    openHelp() {
      this.showHelp = true;
    },

    closeHelp() {
      this.showHelp = false;
    },

    onChatPanelOpenSettings(activeTab) {
      this.openSettings(activeTab);
    },

    onThemeUpdated(updatedUser) {
      // Update user data with new theme
      this.user = { ...this.user, ...updatedUser };

      // Apply the new theme
      this.applyTheme();
    },

    applyTheme() {
      const theme = this.user?.theme || "dark";
      document.documentElement.setAttribute("data-theme", theme);
    },

    // Chat context management methods
    addBlockToContext(block, parentUuid = null) {
      // Don't add if already in context
      if (!this.chatContextBlocks.find((b) => b.uuid === block.uuid)) {
        this.chatContextBlocks.push({
          uuid: block.uuid,
          content: block.content,
          block_type: block.block_type,
          created_at: block.created_at,
          parent_uuid: parentUuid,
        });
      }

      // Recursively add all child blocks
      if (block.children && block.children.length) {
        block.children.forEach((child) => {
          this.addBlockToContext(child, block.uuid);
        });
      }
    },

    removeBlockFromContext(blockUuid) {
      // Get all block UUIDs to remove (block + all descendants)
      const uuidsToRemove = this.getBlockAndDescendantUuids(blockUuid);

      // Remove all blocks (parent + descendants) from context
      this.chatContextBlocks = this.chatContextBlocks.filter(
        (b) => !uuidsToRemove.includes(b.uuid)
      );
    },

    getBlockAndDescendantUuids(blockUuid) {
      const uuidsToRemove = [blockUuid];

      // Use the stored parent relationships to find descendants
      const findDescendantsInContext = (parentUuid) => {
        const children = this.chatContextBlocks.filter(
          (block) => block.parent_uuid === parentUuid
        );

        children.forEach((child) => {
          uuidsToRemove.push(child.uuid);
          // Recursively find grandchildren
          findDescendantsInContext(child.uuid);
        });
      };

      // Find all descendants using the context relationships
      findDescendantsInContext(blockUuid);

      return uuidsToRemove;
    },

    isBlockInContext(blockUuid) {
      return this.chatContextBlocks.some((b) => b.uuid === blockUuid);
    },

    clearChatContext() {
      this.chatContextBlocks = [];
    },

    updateVisibleBlocks(blocks) {
      this.visibleBlocks = blocks;
    },

    onBlockAddToContext(block) {
      this.addBlockToContext(block);
    },

    onBlockRemoveFromContext(blockId) {
      this.removeBlockFromContext(blockId);
    },

    onPageLoaded(page) {
      this.currentPagePageType = page?.page_type || null;
    },

    async createNewPage(prefilledTitle = null, pageType = "page") {
      const title =
        prefilledTitle ??
        prompt(
          pageType === "whiteboard"
            ? "Enter whiteboard title:"
            : "Enter page title:"
        );
      if (!title || !title.trim()) return;

      try {
        // Generate a simple slug from the title
        const slug = title
          .toLowerCase()
          .replace(/[^a-z0-9\s-]/g, "")
          .replace(/\s+/g, "-")
          .replace(/-+/g, "-")
          .trim("-");

        const result = await window.apiService.createPage(
          title.trim(),
          slug,
          true,
          pageType
        );

        if (result.success) {
          // Navigate to the new page
          window.location.href = `/knowledge/page/${slug}/`;
        } else {
          alert(
            "Failed to create page: " +
              (result.errors?.title?.[0] || "Unknown error")
          );
        }
      } catch (error) {
        console.error("Failed to create page:", error);
        alert("Failed to create page. Please try again.");
      }
    },

    async createNewWhiteboard(prefilledTitle = null) {
      return this.createNewPage(prefilledTitle, "whiteboard");
    },

    navigateToGraph() {
      window.location.href = "/knowledge/graph/";
    },

    // Fired by child components (CustomEvent 'brainspread:toast', detail = {message, type, duration}).
    // Bridges DOM events into the toast state without coupling the children to this component.
    handleToastEvent(event) {
      const detail = event?.detail || {};
      if (!detail.message) return;
      this.addToast(detail.message, detail.type || "info", detail.duration);
    },

    // Toast notification methods
    addToast(message, type = "info", duration = 5000) {
      const toast = {
        id: this.toastIdCounter++,
        message,
        type,
        duration,
      };

      this.toasts.push(toast);

      // Auto-remove after duration
      if (duration > 0) {
        setTimeout(() => {
          this.removeToast(toast.id);
        }, duration);
      }

      return toast.id;
    },

    removeToast(toastId) {
      const index = this.toasts.findIndex((toast) => toast.id === toastId);
      if (index > -1) {
        this.toasts.splice(index, 1);
      }
    },

    clearAllToasts() {
      this.toasts = [];
    },

    // Global keyboard handler
    handleGlobalKeydown(event) {
      // Cmd+K (Mac) or Ctrl+K (Windows/Linux)
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        if (this.isAuthenticated) {
          this.openSpotlight();
        }
      }

      // Sidebar toggles — Cmd/Ctrl+\ toggles the AI chat panel (right) and
      // Cmd/Ctrl+Shift+\ toggles the left sidebar. No editable-target guard
      // because backslash isn't a text-editing shortcut, so it's safe to
      // intercept even when focus is in the block editor or chat input.
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key === "\\" &&
        this.isAuthenticated
      ) {
        event.preventDefault();
        if (event.shiftKey) {
          this.toggleLeftNav();
        } else {
          this.toggleChatPanel();
        }
        return;
      }

      if (event.key === "Escape") {
        if (this.showSpotlight) {
          this.closeSpotlight();
        } else if (this._isInsideLeftNav(event.target)) {
          // If Escape fires from inside the left nav (e.g., its filter
          // selects have focus), close that sidebar directly. Skips the
          // editable-target guard because the sidebar itself doesn't host
          // any serious editing surface.
          if (this._closeLeftNavIfOpen()) event.preventDefault();
        } else if (!this._isEditableTarget(event.target)) {
          // Escape dismisses any open sidebars, but only when the user isn't
          // typing in a real editor (blocks, chat input). Those have their
          // own Escape handlers.
          const closedLeftNav = this._closeLeftNavIfOpen();
          const closedChat = this._closeChatIfOpen();
          if (closedLeftNav || closedChat) {
            event.preventDefault();
          }
        }
      }
    },

    _isInsideLeftNav(el) {
      const sidebar = this.$refs.leftNav;
      return !!(sidebar && sidebar.$el && sidebar.$el.contains(el));
    },

    _closeLeftNavIfOpen() {
      const sidebar = this.$refs.leftNav;
      if (sidebar && sidebar.isOpen) {
        sidebar.toggleSidebar();
        return true;
      }
      return false;
    },

    _closeChatIfOpen() {
      const panel = this.$refs.chatPanel;
      if (panel && panel.isOpen) {
        panel.togglePanel();
        return true;
      }
      return false;
    },

    _isEditableTarget(el) {
      if (!el) return false;
      const tag = el.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT")
        return true;
      return el.isContentEditable === true;
    },

    // Spotlight search methods
    openSpotlight() {
      this.showSpotlight = true;
      this.spotlightQuery = "";
      this.spotlightResults = this.getCommandResults("");
      this.spotlightSelectedIndex = 0;

      // Focus search input after a brief delay to ensure modal is rendered
      this.$nextTick(() => {
        const searchInput = document.querySelector(".spotlight-search-input");
        if (searchInput) {
          searchInput.focus();
        }
      });
    },

    closeSpotlight() {
      this.showSpotlight = false;
      this.spotlightQuery = "";
      this.spotlightResults = [];
      this.spotlightSelectedIndex = 0;
    },

    getCommandResults(query) {
      const commands = [
        {
          id: "new-page",
          label: "new page",
          description: "create a new page",
          icon: "+",
        },
        {
          id: "new-whiteboard",
          label: "new whiteboard",
          description: "create a new whiteboard",
          icon: "✎",
        },
        {
          id: "new-block",
          label: "new block",
          description: "add a block to the current page",
          icon: "+",
        },
        {
          id: "bulk-delete",
          label: "delete selected blocks",
          description: "delete all currently selected blocks",
          icon: "×",
        },
        {
          id: "bulk-move-to-today",
          label: "move selected to today",
          description: "move all selected blocks to today's daily note",
          icon: "⇨",
        },
        {
          id: "today",
          label: "today",
          description: "go to today's daily note",
          icon: "→",
        },
        {
          id: "graph",
          label: "graph",
          description: "view the knowledge graph",
          icon: "◉",
        },
        {
          id: "toggle-sidebar",
          label: this.isLeftNavOpen() ? "close sidebar" : "open sidebar",
          description: "toggle the left sidebar (⌘⇧\\)",
          icon: "⧉",
        },
        {
          id: "toggle-ai",
          label: this.isChatPanelOpen() ? "close ai" : "open ai",
          description: "toggle the ai chat panel (⌘\\)",
          icon: "✦",
        },
        {
          id: "settings",
          label: "settings",
          description: "open settings",
          icon: "⚙",
        },
        { id: "help", label: "help", description: "open help", icon: "?" },
      ];

      const currentTheme = this.user?.theme || "dark";
      for (const theme of AVAILABLE_THEMES) {
        if (theme.id === currentTheme) continue;
        commands.push({
          id: `theme-${theme.id}`,
          label: `theme: ${theme.label}`,
          description: `switch to the ${theme.label} theme`,
          icon: "◐",
        });
      }

      const q = query.trim().toLowerCase();

      // "new page <title>" — let the user type the title inline
      if (q.startsWith("new page ")) {
        const title = query.trim().slice("new page ".length).trim();
        if (title) {
          return [
            {
              type: "command",
              commandId: "new-page",
              commandArg: title,
              title: `create page "${title}"`,
              description: "create a new page with this title",
              icon: "+",
            },
          ];
        }
      }

      // "new whiteboard <title>" — inline whiteboard title
      if (q.startsWith("new whiteboard ")) {
        const title = query.trim().slice("new whiteboard ".length).trim();
        if (title) {
          return [
            {
              type: "command",
              commandId: "new-whiteboard",
              commandArg: title,
              title: `create whiteboard "${title}"`,
              description: "create a new whiteboard with this title",
              icon: "✎",
            },
          ];
        }
      }

      const filtered = q
        ? commands.filter(
            (c) => c.label.includes(q) || c.description.includes(q)
          )
        : commands;

      return filtered.map((c) => ({
        type: "command",
        commandId: c.id,
        title: c.label,
        description: c.description,
        icon: c.icon,
      }));
    },

    performSpotlightSearchDebounced() {
      if (this.spotlightSearchTimeout) {
        clearTimeout(this.spotlightSearchTimeout);
      }
      this.spotlightSearchTimeout = setTimeout(() => {
        this.performSpotlightSearch();
      }, 300);
    },

    async performSpotlightSearch() {
      const query = this.spotlightQuery.trim();
      const commands = this.getCommandResults(this.spotlightQuery);

      if (!query) {
        this.spotlightResults = commands;
        this.spotlightLoading = false;
        return;
      }

      this.spotlightLoading = true;
      this.spotlightSelectedIndex = 0;

      try {
        const result = await window.apiService.searchPages(query, 10);
        if (result.success) {
          const pages = result.data.pages.map((page) => ({
            type: "page",
            pageType: page.page_type,
            title: page.title,
            slug: page.slug,
            snippet: "",
            url: `/knowledge/page/${page.slug}/`,
          }));
          this.spotlightResults = [...commands, ...pages];
        }
      } catch (error) {
        console.error("Search error:", error);
        this.spotlightResults = commands;
      } finally {
        this.spotlightLoading = false;
      }
    },

    generateSnippet(content, query) {
      if (!content) return "";

      // For title-based search, just return a truncated version of the title
      if (content.length <= 60) {
        return content;
      }

      const lowerContent = content.toLowerCase();
      const lowerQuery = query.toLowerCase();
      const index = lowerContent.indexOf(lowerQuery);

      if (index === -1) {
        return content.substring(0, 60) + (content.length > 60 ? "..." : "");
      }

      const start = Math.max(0, index - 20);
      const end = Math.min(content.length, index + query.length + 20);
      const snippet = content.substring(start, end);

      return (
        (start > 0 ? "..." : "") + snippet + (end < content.length ? "..." : "")
      );
    },

    navigateToSpotlightResult(index = null) {
      const targetIndex = index !== null ? index : this.spotlightSelectedIndex;
      const result = this.spotlightResults[targetIndex];
      if (!result) return;

      this.closeSpotlight();

      if (result.type === "command") {
        this.executeSpotlightCommand(result.commandId, result.commandArg);
      } else {
        window.location.href = result.url;
      }
    },

    isLeftNavOpen() {
      return this.$refs.leftNav?.isOpen === true;
    },

    isChatPanelOpen() {
      return this.$refs.chatPanel?.isOpen === true;
    },

    toggleLeftNav() {
      const sidebar = this.$refs.leftNav;
      if (sidebar && typeof sidebar.toggleSidebar === "function") {
        sidebar.toggleSidebar();
      }
    },

    toggleChatPanel() {
      const panel = this.$refs.chatPanel;
      if (panel && typeof panel.togglePanel === "function") {
        panel.togglePanel();
      }
    },

    executeSpotlightCommand(commandId, arg) {
      if (commandId.startsWith("theme-")) {
        this.setTheme(commandId.slice("theme-".length));
        return;
      }
      switch (commandId) {
        case "new-page":
          this.createNewPage(arg ?? null);
          break;
        case "new-whiteboard":
          this.createNewWhiteboard(arg ?? null);
          break;
        case "new-block":
          document.dispatchEvent(new CustomEvent("spotlight:new-block"));
          break;
        case "bulk-delete":
          document.dispatchEvent(new CustomEvent("spotlight:bulk-delete"));
          break;
        case "bulk-move-to-today":
          document.dispatchEvent(
            new CustomEvent("spotlight:bulk-move-to-today")
          );
          break;
        case "today":
          this.redirectToToday();
          break;
        case "graph":
          this.navigateToGraph();
          break;
        case "toggle-sidebar":
          this.toggleLeftNav();
          break;
        case "toggle-ai":
          this.toggleChatPanel();
          break;
        case "settings":
          this.openSettings();
          break;
        case "help":
          this.openHelp();
          break;
      }
    },

    async setTheme(theme) {
      if (!AVAILABLE_THEMES.some((t) => t.id === theme)) return;
      const previous = this.user?.theme || "dark";
      if (theme === previous) return;

      document.documentElement.setAttribute("data-theme", theme);
      this.user = { ...this.user, theme };

      try {
        const result = await window.apiService.updateUserTheme(theme);
        if (!result || !result.success) {
          throw new Error("updateUserTheme did not succeed");
        }
      } catch (error) {
        console.error("failed to persist theme:", error);
        document.documentElement.setAttribute("data-theme", previous);
        this.user = { ...this.user, theme: previous };
      }
    },

    handleSpotlightKeydown(event) {
      if (!this.spotlightResults.length) return;

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          this.spotlightSelectedIndex = Math.min(
            this.spotlightSelectedIndex + 1,
            this.spotlightResults.length - 1
          );
          break;

        case "ArrowUp":
          event.preventDefault();
          this.spotlightSelectedIndex = Math.max(
            this.spotlightSelectedIndex - 1,
            0
          );
          break;

        case "Enter":
          event.preventDefault();
          this.navigateToSpotlightResult();
          break;
      }
    },
  },

  template: `
        <div class="journals-app" :class="{ 'initial-load': loading && !user }">
            <!-- Show loading during initial auth check to prevent login flash -->
            <div v-if="loading && !user" class="loading-container" style="min-height: 100vh; display: flex; align-items: center; justify-content: center;">
                <div class="loading">Loading...</div>
            </div>

            <!-- Authenticated state -->
            <div v-else-if="isAuthenticated">
                <nav class="navbar">
                    <div class="nav-content">
                        <h1><a href="/knowledge/" class="brand-link">brainspread</a></h1>
                    </div>
                </nav>

                <!-- Toast Notifications -->
                <ToastNotifications
                    :toasts="toasts"
                    @remove-toast="removeToast"
                />

                <main class="main-content">
                    <div v-if="loading" class="loading-container">
                        <div class="loading">Loading...</div>
                    </div>
                    <div v-else-if="currentView === 'graph'" class="graph-layout">
                        <LeftNav
                            ref="leftNav"
                            :user="user"
                            @navigate-to-slug="onNavigateToSlug"
                            @navigate-today="redirectToToday"
                            @navigate-graph="navigateToGraph"
                            @open-search="openSpotlight"
                            @create-page="createNewPage"
                            @create-whiteboard="createNewWhiteboard"
                            @open-settings="openSettings"
                            @open-help="openHelp"
                            @logout="handleLogout" />
                        <GraphView />
                    </div>
                    <div v-else class="content-layout">
                        <LeftNav
                            ref="leftNav"
                            :user="user"
                            @navigate-to-slug="onNavigateToSlug"
                            @navigate-today="redirectToToday"
                            @navigate-graph="navigateToGraph"
                            @open-search="openSpotlight"
                            @create-page="createNewPage"
                            @create-whiteboard="createNewWhiteboard"
                            @open-settings="openSettings"
                            @open-help="openHelp"
                            @logout="handleLogout" />
                        <div class="main-content-area">
                            <Page
                                :chat-context-blocks="chatContextBlocks"
                                :is-block-in-context="isBlockInContext"
                                @block-add-to-context="onBlockAddToContext"
                                @block-remove-from-context="onBlockRemoveFromContext"
                                @visible-blocks-changed="updateVisibleBlocks"
                                @page-loaded="onPageLoaded"
                            />
                        </div>
                        <ChatPanel
                            v-if="showChatPanel"
                            ref="chatPanel"
                            :chat-context-blocks="chatContextBlocks"
                            :visible-blocks="visibleBlocks"
                            @open-settings="onChatPanelOpenSettings"
                            @remove-context-block="onBlockRemoveFromContext"
                            @clear-context="clearChatContext"
                        />
                    </div>
                </main>
            </div>

            <!-- Login state -->
            <main v-else class="main-content">
                <div class="auth-container">
                    <LoginForm @login-success="onLoginSuccess" />
                </div>
            </main>
        </div>

        <!-- Settings Modal -->
        <SettingsModal
            :is-open="showSettings"
            :user="user"
            :active-tab="settingsActiveTab"
            @close="closeSettings"
            @theme-updated="onThemeUpdated"
        />

        <!-- Help Modal -->
        <HelpModal
            :is-open="showHelp"
            @close="closeHelp"
        />

        <!-- Spotlight Search Modal -->
        <SpotlightSearch
            :is-open="showSpotlight"
            :query="spotlightQuery"
            :results="spotlightResults"
            :loading="spotlightLoading"
            :selected-index="spotlightSelectedIndex"
            @close="closeSpotlight"
            @query-changed="spotlightQuery = $event; performSpotlightSearchDebounced()"
            @navigate="navigateToSpotlightResult"
            @keydown="handleSpotlightKeydown"
        />
    `,
});

// Mount the app when DOM is ready
document.addEventListener("DOMContentLoaded", function () {
  KnowledgeApp.mount("#app");
});
