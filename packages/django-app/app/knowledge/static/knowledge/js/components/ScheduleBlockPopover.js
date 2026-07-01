// Schedule Block Popover — set a block's due date and an optional reminder.
//
// Reminder offset chips (day-of, 1d/2d/1w before) compute their concrete
// date from the chosen due date and submit it as `reminder_date`. Pick
// "custom date..." to fire on any day independent of the due date.
//
// Time field defaults to the next "common chunk" (9am, noon, 3pm, 5pm,
// 8pm) for today, or 9am for any future date. If the user manually edits
// the time once, we stop overwriting it for the remainder of this session.
//
// The due value is all-day by default; ticking "at" adds a
// specific time of day (emitted as dueTime; "" means all-day).
//
// Emits: save({ scheduledFor, dueTime, reminderDate, reminderTime }) and cancel.

const SCHEDULE_TIME_CHUNKS = [
  { time: "09:00", label: "9am" },
  { time: "12:00", label: "noon" },
  { time: "15:00", label: "3pm" },
  { time: "17:00", label: "5pm" },
  { time: "20:00", label: "8pm" },
];

const REMINDER_OFFSETS = [
  { value: "day_of", label: "day of", days: 0 },
  { value: "1d_before", label: "1 day before", days: 1 },
  { value: "2d_before", label: "2 days before", days: 2 },
  { value: "1w_before", label: "1 week before", days: 7 },
  { value: "custom", label: "custom date...", days: null },
];

function todayLocalISO(now = new Date()) {
  const tzOffsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

// HH:MM in local time.
function timeHHMM(date) {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

// Both the local-date ISO and HH:MM for the given Date — used by the
// "in 30m" / "in 1h" relative time chips so they can roll the schedule
// date over to tomorrow if "now + offset" crosses midnight.
function localDateTimeISO(date) {
  return { date: todayLocalISO(date), time: timeHHMM(date) };
}

function defaultReminderTimeFor(scheduledFor, now = new Date()) {
  if (!scheduledFor) return "";
  if (scheduledFor !== todayLocalISO(now)) return "09:00";
  const nowMins = now.getHours() * 60 + now.getMinutes();
  for (const chunk of SCHEDULE_TIME_CHUNKS) {
    const [h, m] = chunk.time.split(":").map(Number);
    if (h * 60 + m > nowMins) return chunk.time;
  }
  return "";
}

// Subtract N days from an ISO date string ("YYYY-MM-DD"); returns "" if
// scheduledFor is empty so callers can pass it through unchanged.
function subtractDaysISO(iso, days) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() - days);
  return dt.toISOString().slice(0, 10);
}

function diffDays(laterISO, earlierISO) {
  if (!laterISO || !earlierISO) return null;
  const [y1, m1, d1] = laterISO.split("-").map(Number);
  const [y2, m2, d2] = earlierISO.split("-").map(Number);
  const a = Date.UTC(y1, m1 - 1, d1);
  const b = Date.UTC(y2, m2 - 1, d2);
  return Math.round((a - b) / (1000 * 60 * 60 * 24));
}

function deriveOffset(scheduledFor, pendingDate) {
  if (!pendingDate || !scheduledFor) return "day_of";
  const days = diffDays(scheduledFor, pendingDate);
  const match = REMINDER_OFFSETS.find((o) => o.days === days);
  return match ? match.value : "custom";
}

window.ScheduleBlockPopover = {
  name: "ScheduleBlockPopover",
  props: {
    isOpen: { type: Boolean, default: false },
    initialDate: { type: String, default: "" },
    initialDueTime: { type: String, default: "" },
    initialReminderDate: { type: String, default: "" },
    initialTime: { type: String, default: "" },
  },
  emits: ["save", "cancel"],
  data() {
    return {
      scheduledFor: "",
      dueTimeEnabled: false,
      dueTime: "",
      reminderEnabled: false,
      reminderOffset: "day_of",
      customReminderDate: "",
      reminderTime: "",
      timeManuallyEdited: false,
      offsets: REMINDER_OFFSETS,
      // Refreshed when the popover opens so the relative-time chips
      // ("in 30m", "in 1h") and the past-chunk filter are anchored to
      // when the user actually started looking at the popover, not
      // page-load time.
      nowMs: Date.now(),
    };
  },
  computed: {
    showCustomDate() {
      return this.reminderEnabled && this.reminderOffset === "custom";
    },
    // Concrete date the reminder will fire on, given the current state.
    resolvedReminderDate() {
      if (!this.reminderEnabled) return "";
      if (this.reminderOffset === "custom") return this.customReminderDate;
      const offset = REMINDER_OFFSETS.find(
        (o) => o.value === this.reminderOffset
      );
      return subtractDaysISO(this.scheduledFor, offset?.days ?? 0);
    },
    todayIso() {
      return todayLocalISO(new Date(this.nowMs));
    },
    tomorrowIso() {
      const t = new Date(this.nowMs);
      t.setDate(t.getDate() + 1);
      return todayLocalISO(t);
    },
    // Relative time chips ("in 30m" / "in 1h"). Each preset carries both
    // the target date and target time so the chip can correctly roll
    // the schedule to tomorrow if "now + offset" crosses midnight.
    relativeTimePresets() {
      return [30, 60].map((minutes) => {
        const target = new Date(this.nowMs + minutes * 60_000);
        const { date, time } = localDateTimeISO(target);
        return {
          key: `rel-${minutes}`,
          label: minutes === 60 ? "in 1h" : `in ${minutes}m`,
          date,
          time,
        };
      });
    },
    // Fixed chunk-time chips. When the user is scheduling for today,
    // hide chunks that have already passed so the chip row stays
    // useful instead of offering reminder times that would fire in the
    // past. Future dates show every chunk.
    chunkTimePresets() {
      const isToday = this.scheduledFor === this.todayIso;
      const now = new Date(this.nowMs);
      const nowMins = now.getHours() * 60 + now.getMinutes();
      return SCHEDULE_TIME_CHUNKS.filter(({ time }) => {
        if (!isToday) return true;
        const [h, m] = time.split(":").map(Number);
        return h * 60 + m > nowMins;
      }).map((c) => ({ key: `chunk-${c.time}`, label: c.label, time: c.time }));
    },
  },
  watch: {
    isOpen: {
      handler(open) {
        if (!open) return;
        // Anchor relative-time chips and past-chunk filtering to the
        // moment the popover was opened so they don't drift while
        // the user deliberates.
        this.nowMs = Date.now();
        this.scheduledFor = this.initialDate || todayLocalISO();
        this.dueTimeEnabled = !!this.initialDueTime;
        this.dueTime = this.initialDueTime || "";
        this.reminderEnabled = !!this.initialTime;
        this.reminderTime =
          this.initialTime || defaultReminderTimeFor(this.scheduledFor);
        this.timeManuallyEdited = !!this.initialTime;
        this.reminderOffset = deriveOffset(
          this.scheduledFor,
          this.initialReminderDate
        );
        this.customReminderDate =
          this.reminderOffset === "custom" ? this.initialReminderDate : "";
        this.$nextTick(() => {
          this.$refs.dateInput?.focus();
        });
      },
      immediate: true,
    },
    scheduledFor(newDate) {
      // Re-suggest the default time when the date changes — unless the
      // user has manually picked one this session.
      if (!this.timeManuallyEdited) {
        this.reminderTime = defaultReminderTimeFor(newDate);
      }
      // If the user is on a relative offset (not custom), the reminder
      // date follows the due date implicitly via resolvedReminderDate.
      // Nothing to do for custom — they explicitly picked a date.
    },
  },
  methods: {
    onTimeInput() {
      this.timeManuallyEdited = true;
    },
    onReminderToggle() {
      if (this.reminderEnabled && !this.reminderTime) {
        this.reminderTime =
          defaultReminderTimeFor(this.scheduledFor) || "09:00";
      }
    },
    onDueTimeToggle() {
      // Seed a sensible default so enabling the time doesn't leave the
      // input empty (an empty time would submit as all-day).
      if (this.dueTimeEnabled && !this.dueTime) {
        this.dueTime = "09:00";
      }
    },
    setScheduledFor(iso) {
      this.scheduledFor = iso;
    },
    // Quick-pick chip: jump straight to a specific reminder time. Also
    // enables the reminder so the user doesn't have to tick the box
    // first — tapping a time chip clearly signals they want one.
    pickReminderTime(time, date) {
      if (date) this.scheduledFor = date;
      this.reminderTime = time;
      this.timeManuallyEdited = true;
      this.reminderEnabled = true;
    },
    onOffsetChange() {
      // When switching to custom, seed the input with the due date so the
      // user has a sensible starting point.
      if (this.reminderOffset === "custom" && !this.customReminderDate) {
        this.customReminderDate = this.scheduledFor;
      }
    },
    save() {
      this.$emit("save", {
        scheduledFor: this.scheduledFor || "",
        dueTime: this.scheduledFor && this.dueTimeEnabled ? this.dueTime : "",
        reminderDate: this.reminderEnabled ? this.resolvedReminderDate : "",
        reminderTime: this.reminderEnabled ? this.reminderTime : "",
      });
    },
    cancel() {
      this.$emit("cancel");
    },
    handleBackdropClick(event) {
      if (event.target === event.currentTarget) this.cancel();
    },
    handleKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        this.cancel();
      } else if (event.key === "Enter" && event.target.tagName !== "BUTTON") {
        event.preventDefault();
        this.save();
      }
    },
  },
  template: `
    <div
      v-if="isOpen"
      class="schedule-popover-backdrop"
      @click="handleBackdropClick"
      @keydown="handleKeydown"
    >
      <div class="schedule-popover" role="dialog" aria-label="Schedule block">
        <h3 class="schedule-popover-title">schedule</h3>

        <label class="schedule-popover-row">
          <span class="schedule-popover-label">due</span>
          <input
            ref="dateInput"
            type="date"
            v-model="scheduledFor"
            class="schedule-popover-input"
          />
        </label>

        <div class="schedule-popover-quick-row schedule-popover-quick-row-date">
          <button
            type="button"
            class="schedule-popover-quick-btn"
            :class="{ 'is-active': scheduledFor === todayIso }"
            @click="setScheduledFor(todayIso)"
          >today</button>
          <button
            type="button"
            class="schedule-popover-quick-btn"
            :class="{ 'is-active': scheduledFor === tomorrowIso }"
            @click="setScheduledFor(tomorrowIso)"
          >tomorrow</button>
        </div>

        <label class="schedule-popover-row schedule-popover-row-duetime">
          <input
            type="checkbox"
            v-model="dueTimeEnabled"
            @change="onDueTimeToggle"
            :disabled="!scheduledFor"
          />
          <span class="schedule-popover-label">at</span>
          <input
            type="time"
            v-model="dueTime"
            class="schedule-popover-input"
            :disabled="!dueTimeEnabled || !scheduledFor"
          />
        </label>

        <label class="schedule-popover-row schedule-popover-row-reminder">
          <input
            type="checkbox"
            v-model="reminderEnabled"
            @change="onReminderToggle"
            :disabled="!scheduledFor"
          />
          <span class="schedule-popover-label">remind me</span>
          <select
            v-model="reminderOffset"
            @change="onOffsetChange"
            class="schedule-popover-input"
            :disabled="!reminderEnabled || !scheduledFor"
          >
            <option v-for="o in offsets" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <span class="schedule-popover-label schedule-popover-label-narrow">at</span>
          <input
            type="time"
            v-model="reminderTime"
            @input="onTimeInput"
            class="schedule-popover-input"
            :disabled="!reminderEnabled || !scheduledFor"
          />
        </label>

        <div
          v-if="scheduledFor"
          class="schedule-popover-quick-row schedule-popover-quick-row-time"
        >
          <button
            v-for="preset in relativeTimePresets"
            :key="preset.key"
            type="button"
            class="schedule-popover-quick-btn schedule-popover-quick-btn-relative"
            @click="pickReminderTime(preset.time, preset.date)"
          >{{ preset.label }}</button>
          <span
            v-if="relativeTimePresets.length && chunkTimePresets.length"
            class="schedule-popover-quick-divider"
            aria-hidden="true"
          ></span>
          <button
            v-for="preset in chunkTimePresets"
            :key="preset.key"
            type="button"
            class="schedule-popover-quick-btn"
            :class="{ 'is-active': reminderEnabled && reminderTime === preset.time }"
            @click="pickReminderTime(preset.time)"
          >{{ preset.label }}</button>
        </div>

        <label v-if="showCustomDate" class="schedule-popover-row">
          <span class="schedule-popover-label">on</span>
          <input
            type="date"
            v-model="customReminderDate"
            class="schedule-popover-input"
          />
        </label>

        <p v-if="!scheduledFor" class="schedule-popover-hint">
          pick a date to enable reminders
        </p>

        <div class="schedule-popover-actions">
          <button
            type="button"
            class="btn btn-outline"
            @click="cancel"
          >
            cancel
          </button>
          <button
            type="button"
            class="btn btn-primary"
            @click="save"
          >
            save
          </button>
        </div>
      </div>
    </div>
  `,
};

// Exposed for unit-style testing in the browser console if needed.
window.ScheduleBlockPopover._defaultReminderTimeFor = defaultReminderTimeFor;
window.ScheduleBlockPopover._todayLocalISO = todayLocalISO;
window.ScheduleBlockPopover._subtractDaysISO = subtractDaysISO;
window.ScheduleBlockPopover._deriveOffset = deriveOffset;
