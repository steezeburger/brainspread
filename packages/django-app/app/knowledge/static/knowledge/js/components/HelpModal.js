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

          <div class="help-section" v-pre>
            <h3>variables</h3>
            <p class="help-hint">type <code class="help-syntax">{{</code> in a block to insert a variable; autocomplete lists them as you type. a variable is <strong>filled in once, then frozen</strong> — it resolves when the block is saved (or when a template is applied) and is plain text from then on, so <code class="help-syntax">{{today}}</code> written today still reads today's date next week. that freezing is the point: a <code class="help-syntax">{{count:...}}</code> in a weekly template records one sample per apply, turning a recurring template into a time series.</p>
            <table class="help-table help-table-variables">
              <tbody>
                <tr>
                  <td><code class="help-syntax">today</code> <code class="help-syntax">tomorrow</code> <code class="help-syntax">yesterday</code> <code class="help-syntax">now</code> <code class="help-syntax">current_date</code> <code class="help-syntax">current_time</code></td>
                  <td>dates and times, in your timezone</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">page.title</code> <code class="help-syntax">page.slug</code> <code class="help-syntax">page.date</code> <code class="help-syntax">page.url</code> <code class="help-syntax">page.uuid</code></td>
                  <td>the page the block lives on</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">user.email</code> <code class="help-syntax">user.timezone</code></td>
                  <td>your account</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">uuid</code></td>
                  <td>a fresh id. <code class="help-syntax">{{uuid|name:cart}}</code> gives the <em>same</em> id everywhere that label appears in one template apply — this is how a template wires its own blocks together</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">cursor</code></td>
                  <td>resolves to nothing; marks where the caret should land</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">input:&lt;label&gt;</code></td>
                  <td>asks you for the value when a template is applied, one prompt per label. templates only — a plain block save has nothing to prompt</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">count:&lt;query&gt;</code></td>
                  <td>frozen count of a query, e.g. <code class="help-syntax">{{count:type:todo and completed is null}}</code>. same query language as an automation's <code class="help-syntax">query::</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">&lt;your name&gt;</code></td>
                  <td>your own variables, defined in settings &rarr; variables. an expansion can use other variables and built-ins, e.g. <code class="help-syntax">food_log</code> &rarr; <code class="help-syntax">{{current_time}} #food-log</code>. a variable that refers back to itself is rejected</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">filters chain with <code class="help-syntax">|</code>, jinja-style: <code class="help-syntax">{{now|time}}</code> and <code class="help-syntax">{{now|date}}</code> keep just that half, <code class="help-syntax">{{today|format:%A}}</code> takes any strftime pattern, and <code class="help-syntax">{{uuid|name:&lt;label&gt;}}</code> labels an id. variables inside a template stay dormant until the template is applied. write <code class="help-syntax">\\{{</code> for a literal <code class="help-syntax">{{</code>. an unknown variable or a broken count query is rejected when the block saves, and the error names the full vocabulary.</p>
          </div>

          <div class="help-section">
            <h3>automations</h3>
            <p class="help-hint">any block tagged <span class="inline-tag">#automation</span> (or living on the <code class="help-syntax">automation</code> page) is a live automation, configured with <code class="help-syntax">key:: value</code> lines. example — unfinished work moves itself onto today's daily every morning:</p>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><code class="help-syntax">Morning sweep #automation</code></td>
                  <td>first line = the automation's name (hashtags and inline props are stripped)</td>
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
                  <td><code class="help-syntax">{{today}}</code> <code class="help-syntax">{{now}}</code> <code class="help-syntax">{{count}}</code></td>
                  <td>tokens in action args, frozen once per run — <code class="help-syntax">{{count}}</code> is the matched-block total, e.g. <code class="help-syntax">notify "{{count}} overdue"</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">{{block.tag}}</code> <code class="help-syntax">{{block.content}}</code> <code class="help-syntax">{{block.uuid}}</code> <code class="help-syntax">{{block.page}}</code> <code class="help-syntax">{{block.due}}</code></td>
                  <td>per-block tokens (need a <code class="help-syntax">query::</code>) — the action maps over each matched block, grouping by resolved args, e.g. <code class="help-syntax">move_to_page {{block.tag}}</code> files each block onto the page it's tagged with. bare <code class="help-syntax">{{block.tag}}</code> needs exactly one tag; <code class="help-syntax">{{block.tag|except:slug,…}}</code> excludes tags first. a block left with zero or multiple candidates is skipped, not failed</td>
                </tr>
                <tr>
                  <td><code class="help-syntax">for:: 5,10,15</code> / <code class="help-syntax">5..30 by 5</code></td>
                  <td>iterate a literal list instead of a query, binding <code class="help-syntax">{{item}}</code> — one definition fans out into a whole family, e.g. <code class="help-syntax">create_block "nudge {{item}}m" on today with trigger="schedule every {{item}}m" …</code>. integers, ascending, max 50 items; mutually exclusive with <code class="help-syntax">query::</code></td>
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
