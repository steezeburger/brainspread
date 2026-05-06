const ChatHistory = {
  name: "ChatHistory",
  emits: ["session-selected", "sessions-loaded"],
  data() {
    return {
      sessions: [],
      loading: false,
      error: null,
      isOpen: false,
      // Free-text query forwarded to /api/ai-chat/sessions/?search=. We
      // debounce it locally so each keystroke doesn't fire a request
      // (each one ILIKEs across every message in every session and we
      // don't want to be unkind to the DB).
      searchQuery: "",
      _searchToken: 0,
    };
  },
  async mounted() {
    await this.loadSessions();
    document.addEventListener("chat:sessions-changed", this.onSessionsChanged);
  },
  beforeUnmount() {
    document.removeEventListener("chat:sessions-changed", this.onSessionsChanged);
    if (this._searchTimer) {
      clearTimeout(this._searchTimer);
      this._searchTimer = null;
    }
  },
  methods: {
    async loadSessions(search) {
      this.loading = true;
      this.error = null;
      const myToken = ++this._searchToken;
      try {
        const result = await window.apiService.getChatSessions(search);
        // Drop late responses so a slow query for "foo" doesn't
        // overwrite the fresh result for "foobar".
        if (myToken !== this._searchToken) return;
        if (result.success) {
          this.sessions = result.data;
          this.$emit("sessions-loaded", this.sessions);
        }
      } catch (error) {
        if (myToken !== this._searchToken) return;
        console.error("failed to load chat sessions:", error);
        this.error = "failed to load chat history";
      } finally {
        if (myToken === this._searchToken) {
          this.loading = false;
        }
      }
    },
    toggleHistory() {
      this.isOpen = !this.isOpen;
      if (this.isOpen) {
        this.$nextTick(() => {
          const input = this.$refs.searchInput;
          if (input) input.focus();
        });
      }
    },
    onSearchInput() {
      if (this._searchTimer) clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => {
        this.loadSessions(this.searchQuery);
      }, 200);
    },
    clearSearch() {
      this.searchQuery = "";
      if (this._searchTimer) clearTimeout(this._searchTimer);
      this.loadSessions("");
    },
    onSessionsChanged() {
      // Re-fetch with the current search query so an externally-
      // triggered create / delete (e.g. starting a new chat from a
      // block context menu) updates the list without a reload.
      this.loadSessions(this.searchQuery);
    },
    async selectSession(session) {
      this.$emit("session-selected", session);
      this.isOpen = false; // Close the history panel after selecting a session
    },
    formatDate(dateString) {
      return new Date(dateString).toLocaleDateString();
    },
  },
  template: `
    <div class="chat-history">
      <button class="history-toggle" @click="toggleHistory">
        history ({{ sessions.length }})
      </button>
      <teleport to=".chat-panel" v-if="isOpen">
        <div class="history-dropdown">
          <div class="history-header">
            <h3>chat history</h3>
            <button class="close-btn" @click="toggleHistory">×</button>
          </div>
          <div class="history-search">
            <input
              ref="searchInput"
              v-model="searchQuery"
              type="text"
              class="history-search-input"
              placeholder="search chats…"
              @input="onSearchInput"
              aria-label="Search chat history"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="history-search-clear"
              @click="clearSearch"
              title="Clear search"
              aria-label="Clear search"
            >×</button>
          </div>
          <div class="history-content">
            <div v-if="loading" class="loading">Loading...</div>
            <div v-else-if="error" class="error">{{ error }}</div>
            <div v-else-if="sessions.length === 0" class="empty">
              {{ searchQuery ? 'No chats match this search' : 'No chat history yet' }}
            </div>
            <div v-else class="sessions-list">
              <div
                v-for="session in sessions"
                :key="session.uuid"
                class="session-item"
                @click="selectSession(session)"
              >
                <div class="session-title">{{ session.title }}</div>
                <div
                  v-if="session.match_snippet"
                  class="session-match-snippet"
                >{{ session.match_snippet }}</div>
                <div v-else class="session-preview">{{ session.preview }}</div>
                <div class="session-meta">
                  <span class="session-date">{{ formatDate(session.modified_at) }}</span>
                  <span class="session-count">{{ session.message_count }} messages</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </teleport>
    </div>
  `,
};

window.ChatHistory = ChatHistory;
