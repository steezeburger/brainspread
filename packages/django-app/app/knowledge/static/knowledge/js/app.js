const { createApp } = Vue;

// Global Vue app for knowledge base
const KnowledgeApp = createApp({
  data() {
    const isAuth = window.apiService.isAuthenticated();
    const cachedUser = window.apiService.getCurrentUser();

    return {
      user: cachedUser, // Load user immediately from cache
      isAuthenticated: isAuth, // Check immediately
      currentView: isAuth ? "journal" : "login", // Set view immediately
      loading: isAuth && !cachedUser, // Only show loading if we have token but no cached user
      showSettings: false, // Settings modal state
      settingsActiveTab: "general", // Default tab for settings modal
      showMenu: false, // Menu popover state
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
    };
  },

  components: {
    Page: window.Page,
    LoginForm: window.LoginForm,
    HistoricalSidebar: window.HistoricalSidebar,
    SettingsModal: window.SettingsModal,
    HelpModal: window.HelpModal,
    ChatPanel: window.ChatPanel,
    ToastNotifications: window.ToastNotifications,
    SpotlightSearch: window.SpotlightSearch,
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
  },

  async mounted() {
    console.log("Knowledge app mounted");

    // Apply initial theme
    this.applyTheme();

    // Add event listener for click-outside-to-close menu
    document.addEventListener("click", this.handleDocumentClick);

    // Add global keyboard shortcut listener
    document.addEventListener("keydown", this.handleGlobalKeydown);

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

    // Reapply theme after auth check in case user data was updated
    this.applyTheme();
  },

  beforeUnmount() {
    // Clean up event listeners
    document.removeEventListener("click", this.handleDocumentClick);
    document.removeEventListener("keydown", this.handleGlobalKeydown);
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

    async createNewPage() {
      const title = prompt("Enter page title:");
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
          "",
          slug,
          true
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

    // Menu methods
    toggleMenu() {
      this.showMenu = !this.showMenu;
      if (this.showMenu) {
        this.$nextTick(() => {
          const firstItem = document.querySelector(".menu-popover .menu-item");
          if (firstItem) firstItem.focus();
        });
      }
    },

    closeMenu() {
      this.showMenu = false;
    },

    handleNavMenuKeydown(event) {
      const items = Array.from(
        document.querySelectorAll(".menu-popover .menu-item")
      );
      if (!items.length) return;
      const currentIndex = items.indexOf(document.activeElement);

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          items[Math.min(currentIndex + 1, items.length - 1)].focus();
          break;
        case "ArrowUp":
          event.preventDefault();
          items[Math.max(currentIndex - 1, 0)].focus();
          break;
        case "Escape":
        case "Tab":
          event.preventDefault();
          this.closeMenu();
          this.$nextTick(() => {
            if (this.$refs.menuBtn) this.$refs.menuBtn.focus();
          });
          break;
        case "Home":
          event.preventDefault();
          items[0].focus();
          break;
        case "End":
          event.preventDefault();
          items[items.length - 1].focus();
          break;
      }
    },

    handleDocumentClick(event) {
      // Close menu if clicking outside of it
      const menuContainer = event.target.closest(".menu-container");
      if (!menuContainer && this.showMenu) {
        this.closeMenu();
      }
    },

    // Menu action methods
    onMenuSearch() {
      this.closeMenu();
      this.openSpotlight();
    },

    onMenuCreatePage() {
      this.closeMenu();
      this.createNewPage();
    },

    onMenuSettings() {
      this.closeMenu();
      this.openSettings();
    },

    onMenuHelp() {
      this.closeMenu();
      this.openHelp();
    },

    onMenuLogout() {
      this.closeMenu();
      this.handleLogout();
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

      if (event.key === "Escape") {
        if (this.showSpotlight) {
          this.closeSpotlight();
        } else if (this.showMenu) {
          this.closeMenu();
          this.$nextTick(() => {
            if (this.$refs.menuBtn) this.$refs.menuBtn.focus();
          });
        }
      }
    },

    // Spotlight search methods
    openSpotlight() {
      this.showSpotlight = true;
      this.spotlightQuery = "";
      this.spotlightResults = [];
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

    performSpotlightSearchDebounced() {
      // Clear existing timeout
      if (this.spotlightSearchTimeout) {
        clearTimeout(this.spotlightSearchTimeout);
      }

      // Set new timeout
      this.spotlightSearchTimeout = setTimeout(() => {
        this.performSpotlightSearch();
      }, 300);
    },

    async performSpotlightSearch() {
      if (!this.spotlightQuery.trim()) {
        this.spotlightResults = [];
        this.spotlightLoading = false;
        return;
      }

      this.spotlightLoading = true;
      this.spotlightSelectedIndex = 0;

      try {
        // Use the new dedicated search endpoint
        const result = await window.apiService.searchPages(
          this.spotlightQuery,
          10
        );

        if (result.success) {
          this.spotlightResults = result.data.pages.map((page) => ({
            type: "page",
            title: page.title,
            slug: page.slug,
            snippet: "", // No snippet needed since we only search titles/slugs
            url: `/knowledge/page/${page.slug}/`,
          }));
        }
      } catch (error) {
        console.error("Search error:", error);
        this.spotlightResults = [];
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

      if (result) {
        this.closeSpotlight();
        window.location.href = result.url;
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
                        <div class="nav-right">
                            <span class="user-info">hello, {{ user?.email }}</span>
                            <div class="menu-container">
                                <button @click="toggleMenu" ref="menuBtn" class="menu-btn" :aria-expanded="showMenu" aria-haspopup="menu">
                                    menu
                                </button>
                                <div v-if="showMenu" class="menu-popover" @click.stop @keydown="handleNavMenuKeydown" role="menu">
                                    <button @click="onMenuSearch" class="menu-item" role="menuitem">
                                        search
                                    </button>
                                    <button @click="onMenuCreatePage" class="menu-item" role="menuitem">
                                        + page
                                    </button>
                                    <button @click="onMenuSettings" class="menu-item" role="menuitem">
                                        settings
                                    </button>
                                    <button @click="onMenuHelp" class="menu-item" role="menuitem">
                                        help
                                    </button>
                                    <button @click="onMenuLogout" class="menu-item" role="menuitem">
                                        logout
                                    </button>
                                </div>
                            </div>
                        </div>
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
                    <div v-else class="content-layout">
                        <HistoricalSidebar 
                            @navigate-to-date="onNavigateToDate"
                            @navigate-to-slug="onNavigateToSlug" />
                        <div class="main-content-area">
                            <Page
                                :chat-context-blocks="chatContextBlocks"
                                :is-block-in-context="isBlockInContext"
                                @block-add-to-context="onBlockAddToContext"
                                @block-remove-from-context="onBlockRemoveFromContext"
                                @visible-blocks-changed="updateVisibleBlocks"
                            />
                        </div>
                        <ChatPanel
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
