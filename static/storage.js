// ── USER RANGE STORAGE (localStorage) ────────────────
// Server ranges: read-only, fetched from /api/ranges/list
// User ranges:   stored in localStorage, prefix "user:"

const UserStorage = {

  PREFIX: 'range:',
  LIST_KEY: 'range:__list__',

  // ── SAVE ─────────────────────────────────────────────
  save(filename, rangeData) {
    try {
      const key = this.PREFIX + filename;
      localStorage.setItem(key, JSON.stringify(rangeData));
      // Add to list if not already there
      const list = this.list();
      if (!list.includes(filename)) {
        list.push(filename);
        localStorage.setItem(this.LIST_KEY, JSON.stringify(list));
      }
      return true;
    } catch (e) {
      console.error('Storage save error:', e);
      return false;
    }
  },

  // ── LOAD ─────────────────────────────────────────────
  load(filename) {
    try {
      const raw = localStorage.getItem(this.PREFIX + filename);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      console.error('Storage load error:', e);
      return null;
    }
  },

  // ── DELETE ───────────────────────────────────────────
  delete(filename) {
    try {
      localStorage.removeItem(this.PREFIX + filename);
      const list = this.list().filter(f => f !== filename);
      localStorage.setItem(this.LIST_KEY, JSON.stringify(list));
      return true;
    } catch (e) {
      return false;
    }
  },

  // ── LIST ─────────────────────────────────────────────
  list() {
    try {
      const raw = localStorage.getItem(this.LIST_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  },

  // ── EXPORT (download as JSON file) ───────────────────
  exportFile(filename) {
    const data = this.load(filename);
    if (!data) return false;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = filename.endsWith('.json') ? filename : filename + '.json';
    a.click();
    URL.revokeObjectURL(url);
    return true;
  },

  // ── IMPORT (from file input) ──────────────────────────
  async importFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => {
        try {
          const data = JSON.parse(e.target.result);
          const filename = file.name.replace(/\.json$/, '');
          const ok = this.save(filename, data);
          resolve(ok ? filename : null);
        } catch (err) {
          reject(err);
        }
      };
      reader.onerror = reject;
      reader.readAsText(file);
    });
  },

  // ── BUILD FILE LIST ENTRY (same shape as server) ─────
  toFileEntry(filename) {
    const data = this.load(filename);
    if (!data) return null;
    return {
      filename:    'user:' + filename,
      label:       (data.meta?.label || filename) + ' ★',
      game_type:   data.meta?.game_type   || 'Unknown',
      table_size:  data.meta?.table_size  || '',
      stack_depth: data.meta?.stack_depth || '',
      source:      'user',
    };
  },

  // ── GET ALL AS FILE ENTRIES ───────────────────────────
  allFileEntries() {
    return this.list()
      .map(f => this.toFileEntry(f))
      .filter(Boolean);
  },
};
