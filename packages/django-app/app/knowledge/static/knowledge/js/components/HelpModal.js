// Help Modal Component
window.HelpModal = {
  props: {
    isOpen: {
      type: Boolean,
      default: false,
    },
  },

  emits: ["close"],

  watch: {
    isOpen(newValue) {
      if (newValue) {
        this.$nextTick(() => {
          const body = this.$refs.modalBody;
          if (body) body.focus();
        });
      }
    },
  },

  methods: {
    handleModalKeydown(event) {
      if (event.key === "Escape") {
        this.$emit("close");
        return;
      }
      if (event.key === "Tab") {
        const modal = this.$el?.querySelector(".settings-modal-content");
        if (!modal) return;
        const focusable = Array.from(
          modal.querySelectorAll(
            'button:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );
        if (focusable.length < 2) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
  },

  template: `
    <div v-if="isOpen" class="settings-modal" @click.self="$emit('close')" @keydown="handleModalKeydown">
      <div class="settings-modal-content help-modal-content">
        <div class="help-modal-header">
          <h2>help</h2>
          <button @click="$emit('close')" class="help-close-btn" title="Close">×</button>
        </div>

        <div class="help-modal-body" ref="modalBody" tabindex="-1">
          <div class="help-section">
            <h3>text formatting</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><code class="help-syntax">**bold**</code> or <code class="help-syntax">__bold__</code></td>
                  <td><strong>bold</strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">*italic*</code> or <code class="help-syntax">_italic_</code></td>
                  <td><em>italic</em></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">***bold italic***</code></td>
                  <td><strong><em>bold italic</em></strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">~~strikethrough~~</code></td>
                  <td><s>strikethrough</s></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\`code\`</code></td>
                  <td><code class="markdown-code">code</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">==highlight==</code></td>
                  <td><span class="markdown-highlight">highlight</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">&gt; blockquote</code></td>
                  <td><span class="markdown-quote">blockquote</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">#tagname</code></td>
                  <td><span class="inline-tag">#tagname</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">:grimacing:</code></td>
                  <td>😬 &mdash; toggle in settings &rarr; emoji</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\\*</code></td>
                  <td>escape a special character</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>command palette</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>K</kbd> / <kbd>Ctrl</kbd> + <kbd>K</kbd></td>
                  <td>open the command palette</td>
                </tr>
                <tr>
                  <td><kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>navigate results</td>
                </tr>
                <tr>
                  <td><kbd>Enter</kbd></td>
                  <td>select</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>close</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">search pages or run commands (new page, new block, today, settings, help). type <code class="help-syntax">new page &lt;title&gt;</code> to create a page with that title directly.</p>
          </div>

          <div class="help-section">
            <h3>sidebars</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>\\</kbd> / <kbd>Ctrl</kbd> + <kbd>\\</kbd></td>
                  <td>toggle left sidebar</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>\\</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>\\</kbd></td>
                  <td>toggle ai chat panel</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>close any open sidebar (when not typing)</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">the command palette also has "open/close sidebar" and "open/close ai" entries, which flip labels to match the current state.</p>
          </div>

          <div class="help-section">
            <h3>block editing</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>Enter</kbd></td>
                  <td>new block</td>
                </tr>
                <tr>
                  <td><kbd>Tab</kbd></td>
                  <td>indent block</td>
                </tr>
                <tr>
                  <td><kbd>Shift</kbd> + <kbd>Tab</kbd></td>
                  <td>outdent block</td>
                </tr>
                <tr>
                  <td><kbd>Backspace</kbd> on empty block</td>
                  <td>delete block</td>
                </tr>
                <tr>
                  <td><kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>navigate between blocks</td>
                </tr>
                <tr>
                  <td><kbd>Alt</kbd> + <kbd>Shift</kbd> + <kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>move block up / down</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>⌫</kbd></td>
                  <td>delete block</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>.</kbd> or <kbd>Shift</kbd> + <kbd>F10</kbd></td>
                  <td>open block actions menu</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>S</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>S</kbd></td>
                  <td>schedule (set due date / reminder)</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>;</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>;</kbd></td>
                  <td>open ai chat for this block (writes nested results)</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>exit editing (keeps focus on block for tabbing)</td>
                </tr>
                <tr>
                  <td>double <kbd>space</kbd> at start</td>
                  <td>indent block (mobile)</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>block actions</h3>
            <p class="help-hint">click the <strong>⋮</strong> button, <kbd>Tab</kbd> to it, or press <kbd>⌘</kbd>+<kbd>.</kbd> while focused on a block to open the actions menu: indent, outdent, move up/down, create before/after, add to AI context, and delete. inside the menu, use <kbd>↑</kbd><kbd>↓</kbd> to navigate, <kbd>Enter</kbd> to select, <kbd>Esc</kbd> to close.</p>
          </div>

          <div class="help-section">
            <h3>automations</h3>
            <p class="help-hint">any block tagged <span class="inline-tag">#automation</span> (or living on the <code class="help-syntax">automation</code> page) is a live automation, configured with <code class="help-syntax">key:: value</code> lines. example — unfinished work moves itself onto today's daily every morning:</p>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><code class="help-syntax">Morning sweep #automation</code></td>
                  <td>first line = name (and the slug used to run it)</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">trigger:: schedule daily 5:30</code></td>
                  <td>when it runs, in your timezone. also: <code class="help-syntax">manual</code>, <code class="help-syntax">hourly</code>, <code class="help-syntax">weekly mon 9:00</code>, <code class="help-syntax">every 15m</code>, <code class="help-syntax">cron m h dom mon dow</code> (dom×dow are AND-ed, so <code class="help-syntax">cron 0 5 15-21 * 3</code> = third wednesday)</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">query:: type:todo,doing and due &lt; today</code></td>
                  <td>which blocks it acts on. predicates: <code class="help-syntax">tag:</code> <code class="help-syntax">type:</code> <code class="help-syntax">page_type:</code> <code class="help-syntax">content:"…"</code> <code class="help-syntax">has:</code> <code class="help-syntax">prop:k=v</code> <code class="help-syntax">due_has_time:</code>, due/completed comparisons (<code class="help-syntax">due &lt;= now</code>, <code class="help-syntax">completed &gt;= "7 days ago"</code>, <code class="help-syntax">due is null</code>), combined with <code class="help-syntax">and / or / not</code> and parentheses. or reference a saved view: <code class="help-syntax">view:&lt;slug&gt;</code>. plain text = content search. use <code class="help-syntax">tag:x</code>, never <code class="help-syntax">#x</code> — a literal hashtag would tag the automation itself</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">action:: move_to_daily today</code></td>
                  <td>what it does (one verb): <code class="help-syntax">move_to_daily</code>, <code class="help-syntax">move_to_page "ref"</code>, <code class="help-syntax">set_type done</code>, <code class="help-syntax">tag</code>/<code class="help-syntax">untag &lt;slug&gt;</code>, <code class="help-syntax">set_due &lt;date&gt; [HH:MM] [remind [date] HH:MM]…</code> (<code class="help-syntax">none</code> clears), <code class="help-syntax">set_property key value</code>, <code class="help-syntax">create_block "…" on &lt;date|page&gt; [as type] [tagged slug…] [with k=v…] [due …] [remind …]</code>, <code class="help-syntax">notify "…"</code> (discord; silent when nothing matches), <code class="help-syntax">apply_template "…" to today</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">enabled:: false</code></td>
                  <td>pause ambient runs; an explicit manual run still works (with confirmation). <code class="help-syntax">allow::</code> is optional — omitted grants exactly the declared verb</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">date tokens: <code class="help-syntax">today</code> <code class="help-syntax">tomorrow</code> <code class="help-syntax">yesterday</code> <code class="help-syntax">+3d</code> <code class="help-syntax">-1w</code> or ISO dates; queries also take <code class="help-syntax">now</code> (exact time) and <code class="help-syntax">"N days ago"</code>. definitions inside templates stay dormant until the template is applied. run one on demand from its block's <strong>⋮</strong> menu ("run automation") or by asking the ai chat. every run is recorded — check the admin's automation runs if something misbehaves.</p>
          </div>
        </div>
      </div>
    </div>
  `,
};
