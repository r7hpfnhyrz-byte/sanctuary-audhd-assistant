/* ==========================================================================
   Sanctuary • Interactive Client Controller for AuDHD Assistant & Coach
   Direct Deep-Link & 1-Click Launch + Auto-Complete Engine
   ========================================================================== */

const App = {
  state: {
    briefing: null,
    selectedHorizon: '1d',
    emails: [],
    ideas: [],
    vault: null,
    selectedVaultWindow: 'week',
    pinnedTask: null,
    timerSeconds: 15 * 60,
    timerRunning: false,
    timerInterval: null,
  },

  async init() {
    this.checkSecurity();
    await Promise.all([
      this.loadBriefing(),
      this.loadEmails(),
      this.loadIdeas(),
      this.loadVault('week'),
      this.loadCoachMessages(),
    ]);
  },

  async checkSecurity() {
    try {
      const health = await this.api('/api/health');
      const isProtected = health && health.config && health.config.password_protected;
      document.getElementById('security-banner').classList.toggle('hidden', Boolean(isProtected));
    } catch (_) {}
  },

  async api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    return res.json();
  },

  /* ------------------------------------------------------------------------
     DOPAMINE TOASTS, CONFETTI & AUDIO FEEDBACK
     ------------------------------------------------------------------------ */
  showToast(message) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'dopamine-toast';
    el.innerHTML = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, 4200);
  },

  playChime(isBoss = false) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const notes = isBoss ? [523.25, 659.25, 783.99, 1046.5] : [587.33, 880];
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.08, ctx.currentTime + idx * 0.09);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.09 + 0.35);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime + idx * 0.09);
        osc.stop(ctx.currentTime + idx * 0.09 + 0.36);
      });
    } catch (_) {}
  },

  /* ------------------------------------------------------------------------
     DIRECT TARGET LAUNCHER & 1-CLICK AUTO-COMPLETE ENGINE
     ------------------------------------------------------------------------ */
  async launchAndCompleteSuggestion(id, isBoss = false, autoComplete = true) {
    const res = await this.api('/api/actions/launch-and-complete', 'POST', {
      id,
      auto_complete: autoComplete,
    });
    if (!res.ok) return;

    const launched = res.launched || {};
    // If target is internal #inbox tab, switch immediately
    if (launched.target_url === '#inbox') {
      this.switchTab('inbox');
    } else if (!launched.opened_locally && launched.target_url && launched.target_url.startsWith('http')) {
      window.open(launched.target_url, '_blank', 'noopener');
    }

    if (launched.opened_locally) {
      this.showToast(`📂 Opened "${this.escape(launched.file_basename)}" directly from your Google Drive!`);
    } else if (res.inline_effect) {
      this.showToast(`⚡ ${this.escape(res.inline_effect)}`);
    }

    if (autoComplete) {
      this.clearPinnedTask();
      this.playChime(isBoss);
      this.updateHUD(res.progress);
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    } else if (res.pinned_item) {
      this.pinActiveTask(res.pinned_item, isBoss);
    }
  },

  async openDirectTarget(localFilePath, targetUrl, label = 'Target') {
    if (targetUrl === '#inbox') {
      this.switchTab('inbox');
      return;
    }
    if (targetUrl === '#sandbox') {
      this.switchTab('sandbox');
      return;
    }
    const res = await this.api('/api/actions/open-target', 'POST', {
      local_file_path: localFilePath || '',
      target_url: targetUrl || '',
    });
    const launched = (res && res.launched) || {};
    if (launched.opened_locally) {
      this.showToast(`📂 Opened "${this.escape(launched.file_basename || label)}" on your Mac!`);
    } else if (targetUrl && targetUrl.startsWith('http')) {
      window.open(targetUrl, '_blank', 'noopener');
    }
  },

  pinActiveTask(item, isBoss = false) {
    this.state.pinnedTask = item;
    const bar = document.getElementById('pinned-task-bar');
    bar.classList.remove('hidden');
    document.getElementById('pinned-task-title').textContent = this.splitTitle(item.title).title;

    document.getElementById('pinned-complete-btn').onclick = async () => {
      await this.completeSuggestion(item.id, isBoss);
      this.clearPinnedTask();
    };
    document.getElementById('pinned-reopen-btn').onclick = () => {
      this.openDirectTarget(item.local_file_path, item.target_url, item.target_label);
    };
  },

  clearPinnedTask() {
    this.state.pinnedTask = null;
    const bar = document.getElementById('pinned-task-bar');
    if (bar) bar.classList.add('hidden');
  },

  /* ------------------------------------------------------------------------
     HUD & ENERGY / SPOON CAPACITY SWITCHER
     ------------------------------------------------------------------------ */
  updateHUD(progress) {
    if (!progress) return;
    // XP is still recorded by the backend but deliberately not shown anywhere
    document.querySelectorAll('.spoon-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === progress.energy_mode);
    });

    if (progress.last_reward) {
      const reason = String(progress.last_reward.reason || '')
        .replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, '')
        .replace(
        /^(Cleared: |Next thing done: )(.*)$/,
        (_, prefix, title) => `Done: ${this.splitTitle(title).title}`
      );
      this.showToast(`✓ ${this.escape(reason)}`);
    }
  },

  async setEnergyMode(mode) {
    const res = await this.api('/api/energy-mode', 'POST', { mode });
    if (res.ok) {
      this.state.briefing = res.briefing;
      this.updateHUD(res.progress);
      this.renderBriefing();
      await this.loadEmails();
      if (res.progress.grace_shield_just_activated) {
        this.playChime(false);
        this.showToast('Low spoons on. Only the essentials are showing.');
      } else {
        const names = { high: 'High focus', steady: 'Steady', low_spoons: 'Low spoons' };
        this.showToast(`${names[mode] || mode} on.`);
      }
    }
  },

  switchTab(tabId) {
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-view').forEach((view) => {
      view.classList.toggle('active', view.id === `tab-${tabId}`);
    });
    if (tabId === 'vault') this.loadVault(this.state.selectedVaultWindow);
  },

  toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    document.getElementById('theme-toggle-btn').textContent = next === 'dark' ? '☀️' : '🌙';
  },

  /* ------------------------------------------------------------------------
     60-SECOND QUICK-WIN ROULETTE (1-Click Launch & Auto-Complete!)
     ------------------------------------------------------------------------ */
  async spinRoulette() {
    const res = await this.api('/api/roulette', 'POST');
    if (!res.ok) return;
    const spin = res.roulette;
    const banner = document.getElementById('roulette-banner');
    banner.classList.remove('hidden');
    document.getElementById('roulette-headline').textContent = `${spin.headline}`;
    document.getElementById('roulette-action').textContent = spin.micro_action;

    const doBtn = document.getElementById('roulette-do-btn');
    // Labels from the backend still mention XP ("& Claim +15 XP", "(+35 XP)"); strip that out
    const label = (spin.button_label || 'Do it').replace(/\s*(&\s*)?(Claim\s*)?\(?\+\d+\s*XP\)?/gi, '').trim();
    doBtn.textContent = spin.type === 'email' ? 'Open the reply' : label || 'Do it';
    doBtn.onclick = async () => {
      banner.classList.add('hidden');
      if (spin.type === 'email' && spin.id) {
        // Take them to the drafted reply rather than sending on their behalf
        this.switchTab('inbox');
        const reply = document.querySelector(`[data-reply-id="${spin.id}"]`);
        if (reply) {
          reply.open = true;
          reply.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      } else if (spin.type === 'suggestion' && spin.id) {
        await this.launchAndCompleteSuggestion(spin.id, false, true);
      } else {
        const claim = await this.api('/api/roulette/claim-instant', 'POST', {
          xp: spin.xp_reward,
          reason: spin.headline,
        });
        this.playChime(false);
        this.updateHUD(claim.progress);
      }
    };
  },

  closeRoulette() {
    document.getElementById('roulette-banner').classList.add('hidden');
  },

  /* ------------------------------------------------------------------------
     VIEW 1: DAILY BRIEFING & 4-HORIZON RADAR
     ------------------------------------------------------------------------ */
  async loadBriefing() {
    const data = await this.api('/api/briefing');
    this.state.briefing = data;
    this.updateHUD(data.progress);
    this.renderBriefing();
  },

  renderBriefing() {
    const b = this.state.briefing;
    if (!b) return;

    document.getElementById('current-date-label').textContent = b.generated_at;

    // Sensory & social battery
    const sw = b.sensory_weather || {};
    document.getElementById('weather-social-val').textContent = `${sw.social_load_score}`;
    document.getElementById('weather-social-fill').style.width = `${Math.min(100, sw.social_load_score * 10)}%`;
    document.getElementById('weather-cog-val').textContent = `${sw.cognitive_load_score}`;
    document.getElementById('weather-cog-fill').style.width = `${Math.min(100, sw.cognitive_load_score * 10)}%`;
    document.getElementById('weather-status-label').textContent = sw.status_label || '';

    // At a glance: what's urgent, what's due this week, what's already done
    const c = b.status_counts || {};
    document.getElementById('status-strip').innerHTML = `
      <span class="status-chip u-urgent" title="Across everything Sanctuary has synced"><span class="status-dot"></span>${c.urgent || 0} urgent</span>
      <span class="status-chip u-soon" title="Across everything Sanctuary has synced"><span class="status-dot"></span>${c.soon || 0} this week</span>
      <span class="status-chip is-done">✓ ${c.done_today || 0} done today</span>`;

    // "Your next thing": the single most important task
    const bossContainer = document.getElementById('daily-boss-container');
    if (b.daily_boss) {
      bossContainer.innerHTML = this.renderTaskCard(b.daily_boss, true);
    } else {
      bossContainer.innerHTML = `
        <article class="task-card next-card">
          <div class="next-eyebrow">Your next thing</div>
          <h3 class="card-title">Nothing left at the top of your list.</h3>
        </article>
      `;
    }

    // Horizon counts (the next thing is shown above, so it isn't counted twice)
    ['1d', '2d', '1w', '1m'].forEach((h) => {
      const count = this.horizonSuggestions(h).length;
      const el = document.getElementById(`h-count-${h}`);
      if (el) el.textContent = count;
    });

    this.renderSelectedHorizon();
  },

  horizonSuggestions(h) {
    const b = this.state.briefing;
    const bossId = b.daily_boss ? b.daily_boss.id : null;
    return ((b.horizons && b.horizons[h]) || []).filter((s) => s.id !== bossId);
  },

  // Live Notion titles arrive as "⏰ [Category • Hard Deadline • Priority: High] Title"
  // or "Notion: Title". Pull the tags out so the title reads cleanly.
  splitTitle(raw) {
    let title = String(raw || '').trim();
    let isDeadline = title.startsWith('⏰');
    title = title.replace(/^⏰\s*/, '').replace(/^⚔️?\s*/, '');
    let tags = [];
    const m = title.match(/^\[([^\]]+)\]\s*(.*)$/);
    if (m) {
      tags = m[1].split('•').map((x) => x.trim()).filter(Boolean);
      title = m[2];
    }
    title = title.replace(/^Notion:\s*/, '');
    if (tags.includes('Hard Deadline')) isDeadline = true;
    tags = tags.filter((x) => x !== 'Hard Deadline');
    return { title, tags, isDeadline };
  },

  renderTaskMeta(s, t) {
    const bits = [];
    if (s.due_context) bits.push(this.escape(this.formatDue(s.due_context)));
    t.tags.forEach((tag) => bits.push(this.escape(tag)));
    if (s.source_label) bits.push(this.escape(s.source_label));
    return `<div class="card-meta">${bits.join(' · ')}</div>`;
  },

  // Colour means urgency and nothing else: red / amber / green, always with a word
  urgencyLabel(urgency) {
    return { urgent: 'Urgent', soon: 'This week', later: 'Can wait' }[urgency] || 'Can wait';
  },

  renderTaskCard(s, isBoss = false) {
    const t = this.splitTitle(s.title);
    const urgency = s.urgency || 'later';
    const isAI = s.assignee === 'ai';
    const starter = this.starterStep(s);
    return `
      <article class="task-card u-${urgency} ${isBoss ? 'next-card' : ''}">
        ${isBoss ? '<div class="next-eyebrow">Your next thing</div>' : ''}
        <div class="task-main">
          <h4 class="card-title clickable-title" onclick="App.launchAndCompleteSuggestion(${s.id}, ${isBoss}, false)" title="Open it">
            ${this.escape(t.title)}
          </h4>
          <div class="card-labels">
            <span class="urgency-label u-${urgency}">${this.urgencyLabel(urgency)}</span>
            <button class="who-chip ${isAI ? 'who-ai' : 'who-me'}" onclick="App.toggleAssignee(${s.id})" title="Click to switch between You and AI can help">
              ${isAI ? '✨ AI can help' : '👤 You'}
            </button>
            ${t.isDeadline ? '<span class="deadline-word">Hard deadline</span>' : ''}
          </div>
          ${this.renderTaskMeta(s, t)}
        </div>
        <div class="task-actions">
          ${isAI && !s.ai_draft ? `<button class="btn-ai btn-sm" onclick="App.askAI(${s.id}, this)">Ask AI</button>` : ''}
          <button class="btn-secondary btn-sm" onclick="App.launchAndCompleteSuggestion(${s.id}, ${isBoss}, false)">Open</button>
          <button class="btn-primary btn-sm" onclick="App.completeSuggestion(${s.id}, ${isBoss})">Done</button>
        </div>
        ${isBoss && starter ? `<p class="next-start"><strong>Start with:</strong> ${this.escape(starter)}</p>` : ''}
        ${this.renderDraft(s)}
        ${this.renderTaskMore(s, isBoss)}
      </article>`;
  },

  renderDraft(s) {
    if (!s.ai_draft) return '';
    return `
      <details class="ai-draft" data-draft-id="${s.id}">
        <summary>✨ AI draft ready</summary>
        <div class="ai-draft-text">${this.escape(s.ai_draft)}</div>
        <div class="card-actions-row">
          <button class="btn-secondary btn-sm" onclick="App.copyDraft(${s.id})">Copy</button>
          <button class="btn-ghost btn-sm" onclick="App.askAI(${s.id}, this)">Write it again</button>
        </div>
      </details>`;
  },

  renderDoneCard(s) {
    const t = this.splitTitle(s.title);
    const when = s.cleared_at ? new Date(s.cleared_at) : null;
    const whenText = when && !Number.isNaN(when.getTime())
      ? `Done at ${when.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
      : 'Done';
    return `
      <article class="task-card is-done">
        <div class="task-main">
          <h4 class="card-title"><span class="done-tick">✓</span> ${this.escape(t.title)}</h4>
          <div class="card-meta">${whenText}${s.source_label ? ` · ${this.escape(s.source_label)}` : ''}</div>
        </div>
        <div class="task-actions">
          <button class="btn-ghost btn-sm" onclick="App.reopenSuggestion(${s.id})" title="Put it back on the list">Undo</button>
        </div>
      </article>`;
  },

  // Older synced items have starter tips that describe buttons which no longer exist
  starterStep(s) {
    const step = s.starter_micro_step || '';
    return /Auto-Complete/i.test(step) ? '' : step;
  },

  // Extra detail tucked behind a "More" toggle so cards stay short
  renderTaskMore(s, isBoss) {
    const steps = (s.micro_steps || []).map((st) => `<li>${this.escape(st)}</li>`).join('');
    // Only special actions (e.g. booking a calendar buffer) keep their own label
    const special = ['calendar_buffer', 'inline_reschedule'].includes(s.inline_action_type);
    const oneGoLabel = special && s.inline_action_label
      ? s.inline_action_label.replace(/^\W+/, '').replace(/\s*\(\+\d+ XP\)\s*$/, '')
      : 'Open and mark done in one go';
    const starter = this.starterStep(s);
    return `
      <details class="card-more" data-more-id="${s.id}">
        <summary>More</summary>
        ${s.why_it_matters ? `<p>${this.escape(s.why_it_matters)}</p>` : ''}
        ${!isBoss && starter ? `<p><strong>Start with:</strong> ${this.escape(starter)}</p>` : ''}
        ${steps ? `<ol class="micro-steps-list">${steps}</ol>` : ''}
        <div class="card-actions-row">
          <button class="btn-ghost" onclick="App.launchAndCompleteSuggestion(${s.id}, ${isBoss}, true)">${this.escape(oneGoLabel)}</button>
          <button class="btn-ghost" onclick="App.breakSuggestionSteps(${s.id})">Break into smaller steps</button>
        </div>
      </details>`;
  },

  // "2026-10-28" -> "Due tomorrow" / "Due Fri 30 Oct" / "Overdue (Mon 12 Jan)". Other text passes through.
  formatDue(ctx) {
    const m = String(ctx).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return ctx;
    const due = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const days = Math.round((due - today) / 86400000);
    const opts = { weekday: 'short', day: 'numeric', month: 'short' };
    if (due.getFullYear() !== today.getFullYear()) opts.year = 'numeric';
    const label = due.toLocaleDateString('en-GB', opts);
    if (days < 0) return `Overdue (${label})`;
    if (days === 0) return 'Due today';
    if (days === 1) return 'Due tomorrow';
    return `Due ${label}`;
  },

  formatTimeRange(start, end) {
    const parse = (v) => {
      const d = new Date(String(v || '').replace(' ', 'T'));
      return Number.isNaN(d.getTime()) ? null : d;
    };
    const s = parse(start);
    if (!s) return this.escape(start);
    const day = s.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
    if (String(start).length <= 10) return day;
    const time = (d) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const e = parse(end);
    return e ? `${day}, ${time(s)} to ${time(e)}` : `${day}, ${time(s)}`;
  },

  selectHorizon(horizon) {
    this.state.selectedHorizon = horizon;
    document.querySelectorAll('[data-horizon]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.horizon === horizon);
    });
    this.renderSelectedHorizon();
  },

  renderSelectedHorizon() {
    const b = this.state.briefing;
    if (!b) return;
    const h = this.state.selectedHorizon;

    const suggestions = this.horizonSuggestions(h);
    const suggList = document.getElementById('horizon-suggestions-list');
    if (suggestions.length === 0) {
      suggList.innerHTML = `
        <p class="empty-note">${
          b.energy_mode === 'low_spoons' && h === '1m'
            ? 'Hidden while you are on Low spoons.'
            : 'Nothing here. You are clear.'
        }</p>`;
    } else {
      suggList.innerHTML = suggestions.map((s) => this.renderTaskCard(s)).join('');
    }

    // Finished today: stays visible (greyed) on the Today view so progress is obvious
    const done = h === '1d' ? b.done_today || [] : [];
    const doneSection = document.getElementById('done-today-section');
    doneSection.classList.toggle('hidden', done.length === 0);
    document.getElementById('done-today-heading').textContent = `Done today (${done.length})`;
    document.getElementById('done-today-list').innerHTML = done.map((s) => this.renderDoneCard(s)).join('');

    const events = (b.events_by_horizon && b.events_by_horizon[h]) || [];
    const evList = document.getElementById('horizon-events-list');
    if (events.length === 0) {
      evList.innerHTML = `<p class="empty-note">No calendar events.</p>`;
    } else {
      evList.innerHTML = events
        .map((ev) => {
          const metaBits = [this.formatTimeRange(ev.start_time, ev.end_time), this.escape(ev.account_label)];
          if (ev.location) metaBits.push(this.escape(ev.location));
          return `
          <article class="task-card event-card">
            <div class="task-main">
              <h4 class="card-title clickable-title" onclick="App.openDirectTarget('${this.escapeAttr(ev.local_file_path)}', '${this.escapeAttr(ev.target_url)}', '${this.escapeAttr(ev.title)}')" title="Open it">
                ${this.escape(ev.title)}
              </h4>
              <div class="card-meta">${metaBits.join(' · ')}</div>
            </div>
            <div class="task-actions">
              <button class="btn-secondary btn-sm" onclick="App.openDirectTarget('${this.escapeAttr(ev.local_file_path)}', '${this.escapeAttr(ev.target_url)}', '${this.escapeAttr(ev.target_label)}')">Open</button>
            </div>
            <details class="card-more">
              <summary>More</summary>
              ${ev.prep_needed ? `<p><strong>Before it (${ev.transition_buffer_mins} min):</strong> ${this.escape(ev.prep_needed)}</p>` : ''}
              <p>Social load ${ev.social_load}/10 · Switching load ${ev.cognitive_load}/10</p>
              <div class="card-actions-row">
                <button class="btn-ghost" onclick="App.openDirectTarget('', '${this.escapeAttr(ev.target_url)}', 'Calendar')">Open in calendar</button>
              </div>
            </details>
          </article>`;
        })
        .join('');
    }
  },

  async completeSuggestion(id, isBoss = false) {
    const res = await this.api('/api/suggestions/complete', 'POST', { id });
    if (res.ok) {
      this.playChime(isBoss);
      this.updateHUD(res.progress);
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  async reopenSuggestion(id) {
    const res = await this.api('/api/suggestions/reopen', 'POST', { id });
    if (res.ok) {
      this.showToast('Put back on your list.');
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  // Every copy of a task in the current briefing (it can be both the next thing and in a list)
  findSuggestions(id) {
    const b = this.state.briefing;
    if (!b) return [];
    const all = [b.daily_boss, ...Object.values(b.horizons || {}).flat(), ...(b.done_today || [])];
    return all.filter((s) => s && s.id === id);
  },

  async toggleAssignee(id) {
    const current = this.findSuggestions(id)[0];
    if (!current) return;
    const next = current.assignee === 'ai' ? 'me' : 'ai';
    const res = await this.api('/api/suggestions/assignee', 'POST', { id, assignee: next });
    if (res.ok) {
      this.findSuggestions(id).forEach((s) => {
        s.assignee = next;
        s.assignee_is_choice = true;
      });
      this.renderBriefing();
    }
  },

  async askAI(id, btn) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Writing...';
    }
    const res = await this.api('/api/suggestions/ai-draft', 'POST', { id });
    if (!res.ok) {
      // Shown on the card (not a toast) so there's time to read the reason
      const card = btn && btn.closest('.task-card');
      if (card) {
        let note = card.querySelector('.ai-error');
        if (!note) {
          note = document.createElement('p');
          note.className = 'ai-error';
          card.appendChild(note);
        }
        note.textContent = res.error || 'AI could not write a draft.';
      } else {
        this.showToast(this.escape(res.error || 'AI could not write a draft.'));
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Ask AI';
      }
      return;
    }
    this.findSuggestions(id).forEach((s) => {
      s.ai_draft = res.draft;
    });
    this.renderBriefing();
    document.querySelectorAll(`[data-draft-id="${id}"]`).forEach((d) => {
      d.open = true;
    });
  },

  async copyDraft(id) {
    const s = this.findSuggestions(id)[0];
    if (!s || !s.ai_draft) return;
    try {
      await navigator.clipboard.writeText(s.ai_draft);
      this.showToast('Copied.');
    } catch (_) {
      this.showToast('Could not copy. Select the text and copy it by hand.');
    }
  },

  async breakSuggestionSteps(id) {
    this.showToast('🧠 Breaking task into tiny 60-second AuDHD micro-steps...');
    const res = await this.api('/api/suggestions/micro-steps', 'POST', { id });
    if (res.ok) {
      await this.loadBriefing();
      // Re-rendering closes the "More" panel, so reopen it to show the new steps
      const more = document.querySelector(`[data-more-id="${id}"]`);
      if (more) more.open = true;
      this.showToast('✨ Micro-steps updated!');
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 2: MULTI-INBOX EMAIL TRIAGE & PROACTIVE DRAFT STUDIO
     ------------------------------------------------------------------------ */
  async loadEmails() {
    const data = await this.api('/api/emails');
    this.state.emails = data.emails || [];
    document.getElementById('nav-email-count').textContent = this.state.emails.length;
    this.renderEmails();
  },

  renderEmails() {
    const container = document.getElementById('triage-email-list');
    if (this.state.emails.length === 0) {
      container.innerHTML = `<p class="empty-note">Nothing waiting. You're clear.</p>`;
      return;
    }

    container.innerHTML = this.state.emails.map((e) => this.renderEmailCard(e)).join('');
  },

  // Older triage text carries XP labels like "(+25 XP)"; drop them
  stripXP(text) {
    return String(text || '').replace(/\s*\(\+\d+\s*XP\)/gi, '');
  },

  renderEmailCard(e) {
    const needsReply = e.urgency === 'action_required';
    const app = e.provider === 'google' ? 'Gmail' : 'Outlook';
    const meta = [`From ${this.escape(e.sender_name)}`, this.escape(e.account_label)];
    if (e.received_at) meta.push(this.formatTimeRange(e.received_at, ''));
    return `
      <article class="task-card ${needsReply ? 'u-urgent' : 'u-later'}" id="email-card-${e.id}">
        <div class="task-main">
          <h4 class="card-title clickable-title" onclick="App.openDirectTarget('', '${this.escapeAttr(e.target_url)}', 'Email')" title="Open in ${app}">
            ${this.escape(e.subject)}
          </h4>
          <div class="card-labels">
            <span class="urgency-label ${needsReply ? 'u-urgent' : 'u-later'}">${needsReply ? 'Needs a reply' : 'Can wait'}</span>
            ${
              e.attachment_label
                ? `<button class="who-chip" onclick="App.openDirectTarget('${this.escapeAttr(e.local_file_path)}', '${this.escapeAttr(e.target_url)}', 'Attachment')">📎 ${this.escape(this.stripXP(e.attachment_label).replace(/^\W+/, ''))}</button>`
                : ''
            }
          </div>
          <div class="card-meta">${meta.join(' · ')}</div>
          ${e.one_line_brief ? `<p class="card-summary">${this.escape(e.one_line_brief)}</p>` : ''}
        </div>
        <div class="task-actions">
          <button class="btn-secondary btn-sm" onclick="App.openDirectTarget('', '${this.escapeAttr(e.target_url)}', 'Email')">Open</button>
          <button class="btn-primary btn-sm" onclick="App.sendEmailDraft(${e.id}, 'draft')" title="Mark as handled">Done</button>
        </div>
        <details class="card-more" data-reply-id="${e.id}">
          <summary>Reply (draft ready)</summary>
          ${e.what_they_need ? `<p><strong>What they need:</strong> ${this.escape(this.stripXP(e.what_they_need))}</p>` : ''}
          <div class="tone-bar">
            <span class="card-meta">Make it:</span>
            <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'shorter')">Shorter</button>
            <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'warmer')">Warmer</button>
            <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'polite_boundary')">Push to next week</button>
          </div>
          <textarea id="draft-box-${e.id}" class="textarea-clean" rows="7">${this.escape(e.draft_reply)}</textarea>
          <div class="card-actions-row">
            ${
              e.can_send
                ? `<button class="btn-primary btn-sm" onclick="App.sendEmailDraft(${e.id}, 'send')">Send</button>
                   <button class="btn-secondary btn-sm" onclick="App.copyAndCompleteEmail(${e.id})">Copy reply</button>`
                : `<button class="btn-primary btn-sm" onclick="App.copyAndCompleteEmail(${e.id})" title="Copies the reply and opens the email so you can paste and send it">Copy reply and open ${app}</button>`
            }
          </div>
        </details>
      </article>`;
  },

  // Copy the draft, open the thread to paste it, and mark the email handled
  async copyAndCompleteEmail(emailId) {
    const box = document.getElementById(`draft-box-${emailId}`);
    const bodyText = box ? box.value : '';
    const email = this.state.emails.find((x) => x.id === emailId);
    try {
      await navigator.clipboard.writeText(bodyText);
      this.showToast('Reply copied. Paste it into the email and send.');
    } catch (_) {
      this.showToast('Could not copy. Select the reply text and copy it by hand.');
      return;
    }
    if (email && email.target_url && email.target_url.startsWith('http')) {
      window.open(email.target_url, '_blank', 'noopener');
    }
    await this.sendEmailDraft(emailId, 'draft', bodyText);
  },

  async submitCustomEmailTriage(event) {
    event.preventDefault();
    const sender = document.getElementById('custom-email-sender').value.trim();
    const subject = document.getElementById('custom-email-subject').value.trim();
    const raw_email_text = document.getElementById('custom-email-body').value.trim();
    const btn = document.getElementById('custom-email-btn');
    if (!raw_email_text) return;

    btn.disabled = true;
    btn.textContent = 'Drafting...';
    const res = await this.api('/api/emails/triage-custom', 'POST', {
      sender_name: sender,
      subject,
      raw_email_text,
    });
    btn.disabled = false;
    btn.textContent = 'Draft a reply';

    if (res.ok) {
      document.getElementById('custom-email-sender').value = '';
      document.getElementById('custom-email-subject').value = '';
      document.getElementById('custom-email-body').value = '';
      this.playChime(false);
      this.showToast('Reply drafted. It is at the top of your Inbox.');
      await this.loadEmails();
    }
  },

  async shiftEmailTone(emailId, tone) {
    this.showToast('Rewriting the draft...');
    const res = await this.api('/api/emails/tone', 'POST', { id: emailId, tone });
    if (res.ok) {
      const box = document.getElementById(`draft-box-${emailId}`);
      if (box) box.value = res.draft_reply;
      this.showToast('Draft updated. Check it before sending.');
    }
  },

  async sendEmailDraft(emailId, action, overrideBody = null) {
    const box = document.getElementById(`draft-box-${emailId}`);
    const bodyText = overrideBody !== null ? overrideBody : (box ? box.value : '');
    const res = await this.api('/api/emails/send', 'POST', {
      id: emailId,
      draft_reply: bodyText,
      action,
    });
    if (!res.ok) {
      this.showToast(this.escape(res.error || 'That did not work.'));
      return;
    }
    this.playChime(false);
    this.updateHUD(res.progress);
    await this.loadEmails();
    await this.loadBriefing();
    await this.loadVault(this.state.selectedVaultWindow);
  },

  /* ------------------------------------------------------------------------
     VIEW 3: SHINY OBJECT IDEA SANDBOX & AUTONOMOUS INCUBATOR
     ------------------------------------------------------------------------ */
  async loadIdeas() {
    const data = await this.api('/api/ideas');
    this.state.ideas = data.ideas || [];
    this.renderIdeas();
  },

  renderIdeas() {
    const container = document.getElementById('idea-dossier-list');
    if (this.state.ideas.length === 0) {
      container.innerHTML = `<p class="empty-note">No ideas parked yet.</p>`;
      return;
    }

    container.innerHTML = this.state.ideas
      .map((item) => {
        const d = item.dossier || {};
        const experiments = (d.micro_experiments || []).map((ex) => `<li>${this.escape(ex)}</li>`).join('');
        const verdict = String(d.priority_guardrail || '').replace(/^\W+/, '');
        const meta = [this.escape(item.category)];
        if (item.viability_score) meta.push(`Viability ${item.viability_score}/100`);
        return `
          <article class="task-card">
            <div class="task-main">
              <h4 class="card-title">${this.escape(item.title)}</h4>
              <div class="card-meta">${meta.join(' · ')}</div>
              ${verdict ? `<p class="card-summary"><strong>Verdict:</strong> ${this.escape(verdict)}</p>` : ''}
            </div>
            <div class="task-actions">
              <button class="btn-secondary btn-sm" onclick="App.openDirectTarget('', '${this.escapeAttr(item.notion_url || 'https://www.notion.so')}', 'Notion')">Open in Notion</button>
            </div>
            <details class="card-more">
              <summary>More</summary>
              ${item.raw_spark ? `<p><em>"${this.escape(item.raw_spark)}"</em></p>` : ''}
              ${d.core_thesis ? `<p><strong>The idea:</strong> ${this.escape(d.core_thesis)}</p>` : ''}
              ${d.why_its_exciting ? `<p><strong>Why it appeals:</strong> ${this.escape(d.why_its_exciting)}</p>` : ''}
              ${d.reality_check ? `<p><strong>Reality check:</strong> ${this.escape(d.reality_check)}</p>` : ''}
              ${experiments ? `<p><strong>Small things to try later:</strong></p><ol class="micro-steps-list">${experiments}</ol>` : ''}
            </details>
          </article>
        `;
      })
      .join('');
  },

  async submitIdea(event) {
    event.preventDefault();
    const titleEl = document.getElementById('idea-title-input');
    const sparkEl = document.getElementById('idea-spark-input');
    const catEl = document.getElementById('idea-category-input');
    const btn = document.getElementById('idea-submit-btn');

    const title = titleEl.value.trim();
    const raw_spark = sparkEl.value.trim();
    const category = catEl.value;
    if (!title) return;

    btn.disabled = true;
    btn.textContent = 'Parking and researching...';

    const res = await this.api('/api/ideas', 'POST', { title, raw_spark, category });
    btn.disabled = false;
    btn.textContent = 'Park idea';

    if (res.ok) {
      titleEl.value = '';
      sparkEl.value = '';
      this.playChime(false);
      this.showToast('Idea parked. Back to what you were doing.');
      await this.loadIdeas();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 4: AuDHD COACH, BODY-DOUBLING TIMER & TASK BREAKER
     ------------------------------------------------------------------------ */
  async loadCoachMessages() {
    const data = await this.api('/api/coach');
    this.renderCoachMessages(data.messages || []);
  },

  renderCoachMessages(messages) {
    const box = document.getElementById('coach-messages-box');
    box.innerHTML = messages
      .map((m) => `<div class="chat-bubble ${m.role === 'user' ? 'user' : 'coach'}">${this.formatBold(m.content.trim())}</div>`)
      .join('');
    box.scrollTop = box.scrollHeight;
  },

  async submitCoachMessage(event) {
    event.preventDefault();
    const input = document.getElementById('coach-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    await this.sendQuickCoach(msg);
  },

  async sendQuickCoach(message) {
    const res = await this.api('/api/coach', 'POST', { message });
    if (res.ok) {
      this.renderCoachMessages(res.messages || []);
    }
  },

  setTimerMinutes(mins) {
    this.resetTimer();
    this.state.timerMinutes = mins;
    this.state.timerSeconds = mins * 60;
    this.updateTimerDisplay();
    document.querySelectorAll('.timer-presets .chip-btn').forEach((b) => {
      b.classList.toggle('active', Number(b.dataset.mins) === mins);
    });
  },

  updateTimerDisplay() {
    const m = String(Math.floor(this.state.timerSeconds / 60)).padStart(2, '0');
    const s = String(this.state.timerSeconds % 60).padStart(2, '0');
    document.getElementById('focus-timer-display').textContent = `${m}:${s}`;
  },

  toggleTimer() {
    const btn = document.getElementById('timer-start-btn');
    if (this.state.timerRunning) {
      clearInterval(this.state.timerInterval);
      this.state.timerRunning = false;
      btn.textContent = 'Resume';
    } else {
      this.state.timerRunning = true;
      btn.textContent = 'Pause';
      this.state.timerInterval = setInterval(async () => {
        if (this.state.timerSeconds > 0) {
          this.state.timerSeconds--;
          this.updateTimerDisplay();
        } else {
          clearInterval(this.state.timerInterval);
          this.state.timerRunning = false;
          btn.textContent = 'Start';
          this.playChime(true);
          this.showToast('Time. You can stop now.');
        }
      }, 1000);
    }
  },

  resetTimer() {
    if (this.state.timerInterval) clearInterval(this.state.timerInterval);
    this.state.timerRunning = false;
    this.state.timerSeconds = (this.state.timerMinutes || 15) * 60;
    this.updateTimerDisplay();
    const btn = document.getElementById('timer-start-btn');
    if (btn) btn.textContent = 'Start';
  },

  async breakDownCustomTask(event) {
    event.preventDefault();
    const input = document.getElementById('custom-task-input');
    const title = input.value.trim();
    if (!title) return;
    this.showToast('Breaking it down...');
    const res = await this.api('/api/tasks/break-down', 'POST', { title });
    if (res.ok) {
      const list = document.getElementById('custom-micro-steps-list');
      list.innerHTML = (res.micro_steps || []).map((s) => `<li>${this.escape(s)}</li>`).join('');
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 5: ACCOMPLISHMENT & CLEARED VAULT (DAY / WEEK / MONTH / YEAR)
     ------------------------------------------------------------------------ */
  async loadVault(windowKey = 'week') {
    this.state.selectedVaultWindow = windowKey;
    document.querySelectorAll('[data-vault-window]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.vaultWindow === windowKey);
    });

    const data = await this.api(`/api/vault?window=${windowKey}`);
    this.state.vault = data;

    if (data.counts_by_window) {
      ['day', 'week', 'month', 'year'].forEach((w) => {
        const el = document.getElementById(`v-count-${w}`);
        if (el) el.textContent = data.counts_by_window[w] || 0;
      });
      document.getElementById('nav-vault-count').textContent = data.counts_by_window.year || data.total_items;
    }

    document.getElementById('vault-celebration-summary').innerHTML = this.formatBold(data.coach_celebration_summary || '');

    const listEl = document.getElementById('vault-items-list');
    const items = data.items || [];
    if (items.length === 0) {
      listEl.innerHTML = `<p class="empty-note">Nothing finished in this period yet.</p>`;
      return;
    }
    listEl.innerHTML = items
      .map((it) => {
        const hasTarget = Boolean(it.local_file_path || it.target_url);
        // Older entries start with decorative emoji ("⚔️ Completed ..."); drop them
        const title = String(it.title || '').replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, '');
        const meta = [this.formatTimeRange(String(it.cleared_at || '').replace('T', ' ').slice(0, 16), '')];
        if (it.account_label) meta.push(this.escape(it.account_label));
        return `
          <article class="task-card done-card">
            <div class="task-main">
              <h4 class="card-title"><span class="done-tick">✓</span> ${this.escape(title)}</h4>
              <div class="card-meta">${meta.join(' · ')}</div>
              ${it.summary ? `<p class="card-summary">${this.escape(this.stripXP(it.summary))}</p>` : ''}
            </div>
            ${
              hasTarget
                ? `<div class="task-actions">
                     <button class="btn-secondary btn-sm" onclick="App.openDirectTarget('${this.escapeAttr(it.local_file_path)}', '${this.escapeAttr(it.target_url)}', '${this.escapeAttr(title)}')">Open</button>
                   </div>`
                : ''
            }
          </article>
        `;
      })
      .join('');
  },

  async syncVaultToNotion() {
    this.showToast('Saving to Notion...');
    const res = await this.api('/api/vault/sync-notion', 'POST');
    const results = (res && res.workspaces_synced) || [];
    const saved = results.find((r) => r.mode === 'live_notion_api' && r.page_url);
    if (saved) {
      this.playChime(false);
      this.showToast('Saved to Notion. Opening the new page so you can see where it went.');
      window.open(saved.page_url, '_blank', 'noopener');
      return;
    }
    // Say plainly why nothing was saved instead of claiming success
    const reason = results.map((r) => r.note || r.warning).find(Boolean);
    this.showToast(this.escape(reason ? `Not saved: ${reason}` : 'Not saved: no Notion page is connected to Sanctuary.'));
  },

  /* ------------------------------------------------------------------------
     MULTI-ACCOUNT MODAL & AI KEYS
     ------------------------------------------------------------------------ */
  async openAccountsModal() {
    document.getElementById('accounts-modal').classList.remove('hidden');
    const data = await this.api('/api/accounts');
    const list = document.getElementById('modal-accounts-list');
    list.innerHTML = (data.accounts || [])
      .map(
        (a) => `
        <div class="modal-acc-item">
          <div>
            <span class="account-dot" style="background:${a.color_tag}; display:inline-block; margin-right:6px;"></span>
            <strong>${this.escape(a.account_label)}</strong> (${this.escape(a.provider.toUpperCase())})
            <div class="source-tag">${this.escape(a.account_identifier)}</div>
          </div>
          <button class="chip-btn" onclick="App.openDirectTarget('', '${this.escapeAttr(a.portal_url || 'https://www.notion.so')}', '${this.escapeAttr(a.account_label)}')">
            Open Workspace ↗
          </button>
        </div>`
      )
      .join('');
  },

  closeAccountsModal() {
    document.getElementById('accounts-modal').classList.add('hidden');
  },

  async addAccount(event) {
    event.preventDefault();
    const provider = document.getElementById('acc-provider').value;
    const account_label = document.getElementById('acc-label').value.trim();
    const account_identifier = document.getElementById('acc-identifier').value.trim();
    const api_token = document.getElementById('acc-token').value.trim();
    const ics_url = (document.getElementById('acc-ics') || {}).value?.trim() || '';
    const app_password = (document.getElementById('acc-app-pass') || {}).value?.trim() || '';
    const res = await this.api('/api/accounts', 'POST', {
      provider,
      account_label,
      account_identifier,
      api_token,
      ics_url,
      app_password,
    });
    if (res.ok) {
      document.getElementById('acc-label').value = '';
      document.getElementById('acc-identifier').value = '';
      document.getElementById('acc-token').value = '';
      if (document.getElementById('acc-ics')) document.getElementById('acc-ics').value = '';
      if (document.getElementById('acc-app-pass')) document.getElementById('acc-app-pass').value = '';
      this.showToast(`✓ Linked ${account_label}! Running live sync...`);
      await this.triggerLiveSync(false);
      await this.openAccountsModal();
    }
  },

  async triggerLiveSync(clearDemoData = false) {
    this.showToast('🔄 Pulling live events, unread emails & Notion pages...');
    const res = await this.api('/api/sync/live', 'POST', {
      clear_demo_data: clearDemoData,
    });
    if (res.ok) {
      this.showToast(
        `✓ Live Sync Complete: ${res.events_synced} events, ${res.emails_triaged} emails triaged, ${res.notion_items_synced} Notion items!`
      );
      if (res.notion_items_synced === 0 && res.notion_debug) {
        this.showToast(`⚠️ Notion: ${this.escape(res.notion_debug)}`);
      }
      await this.loadBriefing();
      await this.loadEmails();
    }
  },

  async saveAIKeys(event) {
    event.preventDefault();
    const gemini_api_key = document.getElementById('key-gemini').value.trim();
    const anthropic_api_key = document.getElementById('key-claude').value.trim();
    const res = await this.api('/api/settings/keys', 'POST', {
      gemini_api_key,
      anthropic_api_key,
    });
    if (res.ok) {
      this.showToast('✓ Dual AI Engine keys (Gemini + Claude) saved!');
      document.getElementById('key-gemini').value = '';
      document.getElementById('key-claude').value = '';
    }
  },

  /* ------------------------------------------------------------------------
     HELPERS
     ------------------------------------------------------------------------ */
  escape(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },

  escapeAttr(str) {
    return String(str || '')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '&quot;');
  },

  formatBold(str) {
    return this.escape(str).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  },
};

window.addEventListener('DOMContentLoaded', () => App.init());
