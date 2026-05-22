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
      // When on, the server filters to favorited sessions only. The
      // pinned section above the chronological list still shows
      // favorites first; this toggle hides the chronological half.
      favoritesOnly: false,
      // uuid of the row currently being renamed inline. Null when no
      // row is in edit mode.
      editingUuid: null,
      editingTitle: "",
      savingTitle: false,
      // Drag-to-reorder state for the Pinned section. Mirrors the
      // LeftNav favorites pattern: dragIndex is the row being dragged,
      // dropIndex is the gap the cursor is hovering between. Both are
      // null when no drag is active. We always operate against the
      // favoritedSessions slice — chronological rows are not draggable.
      favoriteDragIndex: null,
      favoriteDropIndex: null,
    };
  },
  computed: {
    favoritedSessions() {
      return this.sessions.filter((s) => s.is_favorited);
    },
    chronologicalSessions() {
      return this.sessions.filter((s) => !s.is_favorited);
    },
    showPinnedSection() {
      // Hide the "Pinned" header when the favorites filter is on —
      // every row in the list is already a favorite, so a separate
      // section would just be visual noise.
      return !this.favoritesOnly && this.favoritedSessions.length > 0;
    },
  },
  async mounted() {
    await this.loadSessions();
    document.addEventListener("chat:sessions-changed", this.onSessionsChanged);
  },
  beforeUnmount() {
    document.removeEventListener(
      "chat:sessions-changed",
      this.onSessionsChanged
    );
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
        const result = await window.apiService.getChatSessions(
          search,
          this.favoritesOnly
        );
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
      } else {
        this.cancelRename();
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
    toggleFavoritesFilter() {
      this.favoritesOnly = !this.favoritesOnly;
      this.loadSessions(this.searchQuery);
    },
    onSessionsChanged() {
      // Re-fetch with the current search query so an externally-
      // triggered create / delete (e.g. starting a new chat from a
      // block context menu) updates the list without a reload.
      this.loadSessions(this.searchQuery);
    },
    async selectSession(session) {
      // Don't navigate while the user is renaming this row — the
      // click on the input would otherwise bubble up and load the
      // chat, losing their edits.
      if (this.editingUuid === session.uuid) return;
      this.$emit("session-selected", session);
      this.isOpen = false; // Close the history panel after selecting a session
    },
    async toggleFavorite(session) {
      const desired = !session.is_favorited;
      // Optimistic: flip locally so the row jumps to / leaves the
      // pinned section immediately. Re-fetch on success to lock in
      // the server's canonical ordering; revert on failure.
      session.is_favorited = desired;
      try {
        const result = await window.apiService.setChatSessionFavorited(
          session.uuid,
          desired
        );
        if (!result || !result.success) {
          session.is_favorited = !desired;
          return;
        }
        // Reload so the new row order (favorites-first) matches the
        // server's ordering exactly.
        this.loadSessions(this.searchQuery);
      } catch (err) {
        console.error("failed to toggle favorite:", err);
        session.is_favorited = !desired;
      }
    },
    startRename(session) {
      this.editingUuid = session.uuid;
      // Seed the input with the curated title when one exists,
      // otherwise leave it blank so the user starts from scratch
      // rather than editing the context-derived preview.
      this.editingTitle = session.has_title ? session.title : "";
      this.$nextTick(() => {
        const input = this.$refs[`rename-input-${session.uuid}`];
        const el = Array.isArray(input) ? input[0] : input;
        if (el) {
          el.focus();
          el.select();
        }
      });
    },
    cancelRename() {
      this.editingUuid = null;
      this.editingTitle = "";
      this.savingTitle = false;
    },
    async saveRename(session) {
      const trimmed = (this.editingTitle || "").trim();
      if (!trimmed) {
        this.cancelRename();
        return;
      }
      if (session.has_title && trimmed === session.title) {
        this.cancelRename();
        return;
      }
      this.savingTitle = true;
      try {
        const result = await window.apiService.updateChatSessionTitle(
          session.uuid,
          trimmed
        );
        if (result && result.success) {
          session.title = result.data.title;
          session.has_title = true;
        }
      } catch (err) {
        console.error("failed to rename chat:", err);
      } finally {
        this.cancelRename();
      }
    },
    onRenameKeydown(session, event) {
      if (event.key === "Enter") {
        event.preventDefault();
        this.saveRename(session);
      } else if (event.key === "Escape") {
        event.preventDefault();
        this.cancelRename();
      }
    },
    formatDate(dateString) {
      return new Date(dateString).toLocaleDateString();
    },
    onFavoriteDragStart(event, index) {
      this.favoriteDragIndex = index;
      this.favoriteDropIndex = index;
      // Firefox needs setData to actually fire the drag. Payload is
      // irrelevant — the reorder is local component state.
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        try {
          event.dataTransfer.setData("text/plain", String(index));
        } catch (_) {
          // Some sandboxed contexts throw on setData; the drag still
          // works without the payload.
        }
      }
    },
    onFavoriteDragOver(event, index) {
      if (this.favoriteDragIndex === null) return;
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
      // Halve the row to decide before/after — same feel as the
      // LeftNav favorites list.
      const rect = event.currentTarget.getBoundingClientRect();
      const before = event.clientY < rect.top + rect.height / 2;
      this.favoriteDropIndex = before ? index : index + 1;
    },
    onFavoriteDragLeaveList() {
      this.favoriteDropIndex = null;
    },
    async onFavoriteDrop(event) {
      event.preventDefault();
      const fromIndex = this.favoriteDragIndex;
      let toIndex = this.favoriteDropIndex;
      this.favoriteDragIndex = null;
      this.favoriteDropIndex = null;
      if (fromIndex === null || toIndex === null) return;
      if (toIndex > fromIndex) toIndex -= 1;
      if (toIndex === fromIndex) return;

      // Work off the favorited slice — chronological rows aren't
      // drag sources, so a successful drop only ever reorders within
      // the Pinned section.
      const current = this.favoritedSessions;
      const next = current.slice();
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);

      // Optimistic: rebuild this.sessions so the UI snaps before the
      // round-trip. Favorites first (in the new order), then the
      // unchanged chronological tail.
      const previous = this.sessions.slice();
      this.sessions = [...next, ...this.chronologicalSessions];

      try {
        const result = await window.apiService.reorderFavoritedChatSessions(
          next.map((s) => s.uuid)
        );
        if (!result || !result.success) {
          this.sessions = previous;
          this.error = "failed to reorder favorites";
          return;
        }
        // Trust the server's canonical ordering — refetch with current
        // filters so chronological rows / search snippets stay accurate.
        this.loadSessions(this.searchQuery);
      } catch (err) {
        console.error("failed to reorder favorited chats:", err);
        this.sessions = previous;
        this.error = "failed to reorder favorites";
      }
    },
    onFavoriteDragEnd() {
      this.favoriteDragIndex = null;
      this.favoriteDropIndex = null;
    },
    favoriteLabel(session) {
      return session.is_favorited ? "Unpin chat" : "Pin chat";
    },
    favoriteGlyph(session) {
      // Filled vs hollow star — both render as monochrome geometric
      // glyphs per the UI conventions (no emoji).
      return session.is_favorited ? "★" : "☆";
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
          <div class="history-filters">
            <button
              type="button"
              class="history-favorites-toggle"
              :class="{ active: favoritesOnly }"
              @click="toggleFavoritesFilter"
              :title="favoritesOnly ? 'Show all chats' : 'Show favorites only'"
              :aria-pressed="favoritesOnly"
            >{{ favoritesOnly ? '★ Favorites only' : '☆ Show favorites only' }}</button>
          </div>
          <div class="history-content">
            <div v-if="loading" class="loading">Loading...</div>
            <div v-else-if="error" class="error">{{ error }}</div>
            <div v-else-if="sessions.length === 0" class="empty">
              {{
                favoritesOnly
                  ? 'No favorited chats yet'
                  : (searchQuery ? 'No chats match this search' : 'No chat history yet')
              }}
            </div>
            <div v-else class="sessions-list">
              <div v-if="showPinnedSection" class="session-group-header">Pinned</div>
              <template v-if="showPinnedSection">
                <div
                  class="session-pinned-list"
                  @dragleave.self="onFavoriteDragLeaveList"
                  @drop="onFavoriteDrop"
                  @dragover.prevent
                >
                  <template v-for="(session, index) in favoritedSessions" :key="'fav-' + session.uuid">
                    <div
                      v-if="favoriteDropIndex === index && favoriteDragIndex !== null"
                      class="session-pinned-drop-indicator"
                      aria-hidden="true"
                    ></div>
                    <div
                      class="session-item"
                      :class="{
                        favorited: session.is_favorited,
                        renaming: editingUuid === session.uuid,
                        'is-dragging': favoriteDragIndex === index,
                      }"
                      draggable="true"
                      @dragstart="onFavoriteDragStart($event, index)"
                      @dragover="onFavoriteDragOver($event, index)"
                      @dragend="onFavoriteDragEnd"
                      @click="selectSession(session)"
                    >
                      <div class="session-row">
                        <span class="session-pinned-grip" aria-hidden="true" title="Drag to reorder">⋮⋮</span>
                        <button
                          type="button"
                          class="session-favorite-btn favorited"
                          @click.stop="toggleFavorite(session)"
                          :title="favoriteLabel(session)"
                          :aria-label="favoriteLabel(session)"
                        >{{ favoriteGlyph(session) }}</button>
                    <div class="session-main">
                      <div
                        v-if="editingUuid === session.uuid"
                        class="session-rename"
                        @click.stop
                      >
                        <input
                          :ref="'rename-input-' + session.uuid"
                          v-model="editingTitle"
                          type="text"
                          class="session-rename-input"
                          maxlength="200"
                          :disabled="savingTitle"
                          @keydown="onRenameKeydown(session, $event)"
                          @blur="saveRename(session)"
                          aria-label="Rename chat"
                        />
                      </div>
                      <div
                        v-else
                        class="session-title"
                        :class="{ untitled: !session.has_title }"
                        @dblclick.stop="startRename(session)"
                        :title="session.has_title ? 'Double-click to rename' : ''"
                      >{{ session.title }}</div>
                      <div
                        v-if="session.match_snippet"
                        class="session-match-snippet"
                      >{{ session.match_snippet }}</div>
                      <div
                        v-else-if="session.has_title && session.preview"
                        class="session-preview"
                      >{{ session.preview }}</div>
                      <div class="session-meta">
                        <span class="session-date">{{ formatDate(session.modified_at) }}</span>
                        <span class="session-count">{{ session.message_count }} messages</span>
                      </div>
                    </div>
                        <button
                          v-if="editingUuid !== session.uuid"
                          type="button"
                          class="session-rename-btn"
                          @click.stop="startRename(session)"
                          title="Rename chat"
                          aria-label="Rename chat"
                        >✎</button>
                      </div>
                    </div>
                  </template>
                  <div
                    v-if="favoriteDropIndex === favoritedSessions.length && favoriteDragIndex !== null"
                    class="session-pinned-drop-indicator"
                    aria-hidden="true"
                  ></div>
                </div>
                <div v-if="chronologicalSessions.length > 0" class="session-group-header">
                  All chats
                </div>
              </template>
              <div
                v-for="session in (showPinnedSection ? chronologicalSessions : sessions)"
                :key="session.uuid"
                class="session-item"
                :class="{ favorited: session.is_favorited, renaming: editingUuid === session.uuid }"
                @click="selectSession(session)"
              >
                <div class="session-row">
                  <button
                    type="button"
                    class="session-favorite-btn"
                    :class="{ favorited: session.is_favorited }"
                    @click.stop="toggleFavorite(session)"
                    :title="favoriteLabel(session)"
                    :aria-label="favoriteLabel(session)"
                  >{{ favoriteGlyph(session) }}</button>
                  <div class="session-main">
                    <div
                      v-if="editingUuid === session.uuid"
                      class="session-rename"
                      @click.stop
                    >
                      <input
                        :ref="'rename-input-' + session.uuid"
                        v-model="editingTitle"
                        type="text"
                        class="session-rename-input"
                        maxlength="200"
                        :disabled="savingTitle"
                        @keydown="onRenameKeydown(session, $event)"
                        @blur="saveRename(session)"
                        aria-label="Rename chat"
                      />
                    </div>
                    <div
                      v-else
                      class="session-title"
                      :class="{ untitled: !session.has_title }"
                      @dblclick.stop="startRename(session)"
                      :title="session.has_title ? 'Double-click to rename' : ''"
                    >{{ session.title }}</div>
                    <div
                      v-if="session.match_snippet"
                      class="session-match-snippet"
                    >{{ session.match_snippet }}</div>
                    <div
                      v-else-if="session.has_title && session.preview"
                      class="session-preview"
                    >{{ session.preview }}</div>
                    <div class="session-meta">
                      <span class="session-date">{{ formatDate(session.modified_at) }}</span>
                      <span class="session-count">{{ session.message_count }} messages</span>
                    </div>
                  </div>
                  <button
                    v-if="editingUuid !== session.uuid"
                    type="button"
                    class="session-rename-btn"
                    @click.stop="startRename(session)"
                    title="Rename chat"
                    aria-label="Rename chat"
                  >✎</button>
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
