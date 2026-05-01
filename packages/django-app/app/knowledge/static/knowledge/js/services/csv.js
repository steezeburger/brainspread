// CSV parsing for the block renderer. Handles RFC 4180 basics:
//   - fields separated by `delimiter` (defaults to comma)
//   - records separated by LF or CRLF
//   - fields containing the delimiter, a newline, or a double quote
//     must be wrapped in double quotes
//   - an embedded double quote inside a quoted field is escaped as ""
//
// Stays under 100 lines so it can live alongside the rest of the
// vanilla-JS service files without a build step.

(function () {
  function parseCsv(text, delimiter) {
    const sep = delimiter || ",";
    const rows = [];
    let row = [];
    let field = "";
    let inQuotes = false;
    let i = 0;
    const n = text.length;
    while (i < n) {
      const c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i += 2;
            continue;
          }
          inQuotes = false;
          i++;
          continue;
        }
        field += c;
        i++;
        continue;
      }
      if (c === '"') {
        inQuotes = true;
        i++;
        continue;
      }
      if (c === sep) {
        row.push(field);
        field = "";
        i++;
        continue;
      }
      if (c === "\r") {
        if (text[i + 1] === "\n") i++;
        row.push(field);
        field = "";
        rows.push(row);
        row = [];
        i++;
        continue;
      }
      if (c === "\n") {
        row.push(field);
        field = "";
        rows.push(row);
        row = [];
        i++;
        continue;
      }
      field += c;
      i++;
    }
    if (field !== "" || row.length > 0) {
      row.push(field);
      rows.push(row);
    }
    return rows;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // Render parsed CSV rows as a <table> string. The first row is
  // treated as the header — that matches the most common authoring
  // convention and is the only sensible default; users who don't want
  // a header can toggle the block to raw.
  function renderCsvTable(text, delimiter) {
    const rows = parseCsv(text, delimiter);
    if (rows.length === 0) return "";
    const [header, ...body] = rows;
    const headHtml = `<thead><tr>${header
      .map((c) => `<th>${escapeHtml(c)}</th>`)
      .join("")}</tr></thead>`;
    const bodyHtml = body.length
      ? `<tbody>${body
          .map(
            (r) =>
              `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`
          )
          .join("")}</tbody>`
      : "";
    return `<div class="block-csv-scroll"><table class="block-csv">${headHtml}${bodyHtml}</table></div>`;
  }

  window.brainspreadCsv = {
    parseCsv,
    renderCsvTable,
  };
})();
