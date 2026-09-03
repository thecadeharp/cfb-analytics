(() => {
  "use strict";

  const TABLE_SELECTOR = [
    "#view-ratings table",
    "#view-portal table",
    "#view-variance table"
  ].join(", ");

  const state = new WeakMap();

  function installStyles() {
    if (document.getElementById("hammer-sortable-table-styles")) return;

    const style = document.createElement("style");
    style.id = "hammer-sortable-table-styles";

    style.textContent = `
      .hammer-sortable-table thead th[data-sortable-column] {
        position: relative;
        cursor: pointer;
        user-select: none;
        transition:
          color 0.15s ease,
          background 0.15s ease;
      }

      .hammer-sortable-table thead th[data-sortable-column]:hover {
        color: var(--text);
        background: rgba(24, 33, 43, 0.035);
      }

      .hammer-sort-label {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }

      .hammer-sort-arrow {
        display: inline-flex;
        align-items: center;
        justify-content: center;

        width: 13px;
        height: 13px;

        color: var(--muted-light);

        font-family: var(--mono);
        font-size: 10px;
        font-weight: 700;
        line-height: 1;

        opacity: 0.55;
        transition:
          opacity 0.15s ease,
          color 0.15s ease,
          transform 0.15s ease;
      }

      .hammer-sortable-table
      thead
      th[data-sortable-column]:hover
      .hammer-sort-arrow {
        opacity: 1;
      }

      .hammer-sortable-table
      thead
      th[data-sort-direction="asc"],
      .hammer-sortable-table
      thead
      th[data-sort-direction="desc"] {
        color: var(--text);
        background: rgba(24, 33, 43, 0.045);
      }

      .hammer-sortable-table
      thead
      th[data-sort-direction="asc"]
      .hammer-sort-arrow,
      .hammer-sortable-table
      thead
      th[data-sort-direction="desc"]
      .hammer-sort-arrow {
        color: var(--green);
        opacity: 1;
      }

      @media (max-width: 600px) {
        .hammer-sortable-table thead th[data-sortable-column] {
          touch-action: manipulation;
        }

        .hammer-sort-label {
          gap: 5px;
        }

        .hammer-sort-arrow {
          width: 12px;
          font-size: 9px;
        }
      }
    `;

    document.head.appendChild(style);
  }

  function cleanText(value) {
    return String(value ?? "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function isMissing(value) {
    const text = cleanText(value).toLowerCase();

    return (
      text === "" ||
      text === "—" ||
      text === "-" ||
      text === "n/a" ||
      text === "na" ||
      text === "null" ||
      text === "undefined"
    );
  }

  function numericValue(value) {
    const text = cleanText(value);

    if (isMissing(text)) return null;

    /*
      Match the first meaningful signed number in the cell.

      Examples:
      +18.4
      -0.122
      54.6%
      #14
      8.7 pts
      11-2  -> 11

      For ratings tables, the primary displayed number is what
      we want to sort by.
    */

    const match = text.match(/[+-]?(?:\d+(?:,\d{3})*|\d*\.\d+)/);

    if (!match) return null;

    const number = Number(
      match[0].replace(/,/g, "")
    );

    return Number.isFinite(number)
      ? number
      : null;
  }

  function columnLooksNumeric(rows, columnIndex) {
    let numeric = 0;
    let text = 0;

    rows.slice(0, 25).forEach(row => {
      const cell = row.cells[columnIndex];
      if (!cell) return;

      const value = cleanText(cell.textContent);

      if (isMissing(value)) return;

      if (numericValue(value) !== null) {
        numeric += 1;
      } else {
        text += 1;
      }
    });

    return numeric > 0 && numeric >= text;
  }

  function compareMissing(aMissing, bMissing) {
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    return null;
  }

  function compareNumeric(a, b, direction) {
    const aNumber = numericValue(a);
    const bNumber = numericValue(b);

    const missingResult = compareMissing(
      aNumber === null,
      bNumber === null
    );

    if (missingResult !== null) {
      return missingResult;
    }

    return direction === "asc"
      ? aNumber - bNumber
      : bNumber - aNumber;
  }

  function compareText(a, b, direction) {
    const aText = cleanText(a);
    const bText = cleanText(b);

    const missingResult = compareMissing(
      isMissing(aText),
      isMissing(bText)
    );

    if (missingResult !== null) {
      return missingResult;
    }

    const result = aText.localeCompare(
      bText,
      undefined,
      {
        numeric: true,
        sensitivity: "base"
      }
    );

    return direction === "asc"
      ? result
      : -result;
  }

  function resetHeaders(table, activeHeader) {
    table.querySelectorAll(
      "thead th[data-sortable-column]"
    ).forEach(header => {
      if (header === activeHeader) return;

      header.removeAttribute(
        "data-sort-direction"
      );

      const arrow = header.querySelector(
        ".hammer-sort-arrow"
      );

      if (arrow) {
        arrow.textContent = "↕";
      }

      header.setAttribute(
        "aria-sort",
        "none"
      );
    });
  }

  function updateActiveHeader(header, direction) {
    header.setAttribute(
      "data-sort-direction",
      direction
    );

    header.setAttribute(
      "aria-sort",
      direction === "asc"
        ? "ascending"
        : "descending"
    );

    const arrow = header.querySelector(
      ".hammer-sort-arrow"
    );

    if (arrow) {
      arrow.textContent =
        direction === "asc"
          ? "↑"
          : "↓";
    }
  }

  function sortTable(table, columnIndex) {
    const tbody = table.tBodies?.[0];

    if (!tbody) return;

    const rows = Array.from(
      tbody.rows
    );

    if (rows.length < 2) return;

    const currentState =
      state.get(table) ?? {
        column: null,
        direction: null
      };

    const numeric =
      columnLooksNumeric(
        rows,
        columnIndex
      );

    /*
      First click behavior:

      Numeric metric:
      high -> low

      Text/team:
      A -> Z
    */

    let direction;

    if (
      currentState.column === columnIndex
    ) {
      direction =
        currentState.direction === "desc"
          ? "asc"
          : "desc";
    } else {
      direction =
        numeric
          ? "desc"
          : "asc";
    }

    const decoratedRows = rows.map(
      (row, originalIndex) => ({
        row,
        originalIndex,
        value:
          row.cells[columnIndex]
            ?.textContent ?? ""
      })
    );

    decoratedRows.sort((a, b) => {
      const result = numeric
        ? compareNumeric(
            a.value,
            b.value,
            direction
          )
        : compareText(
            a.value,
            b.value,
            direction
          );

      /*
        Stable fallback so equal values don't
        randomly jump around.
      */

      if (result === 0) {
        return (
          a.originalIndex -
          b.originalIndex
        );
      }

      return result;
    });

    const fragment =
      document.createDocumentFragment();

    decoratedRows.forEach(item => {
      fragment.appendChild(item.row);
    });

    tbody.appendChild(fragment);

    const header =
      table.tHead?.rows?.[0]
        ?.cells?.[columnIndex];

    if (header) {
      resetHeaders(table, header);
      updateActiveHeader(
        header,
        direction
      );
    }

    state.set(table, {
      column: columnIndex,
      direction
    });
  }

  function makeHeaderSortable(
    table,
    header,
    columnIndex
  ) {
    if (
      header.hasAttribute(
        "data-sortable-column"
      )
    ) {
      return;
    }

    header.setAttribute(
      "data-sortable-column",
      String(columnIndex)
    );

    header.setAttribute(
      "role",
      "button"
    );

    header.setAttribute(
      "tabindex",
      "0"
    );

    header.setAttribute(
      "aria-sort",
      "none"
    );

    const originalContent =
      header.innerHTML;

    header.innerHTML = `
      <span class="hammer-sort-label">
        <span class="hammer-sort-title">
          ${originalContent}
        </span>
        <span
          class="hammer-sort-arrow"
          aria-hidden="true"
        >↕</span>
      </span>
    `;

    function activate(event) {
      if (
        event.type === "keydown" &&
        event.key !== "Enter" &&
        event.key !== " "
      ) {
        return;
      }

      if (event.type === "keydown") {
        event.preventDefault();
      }

      sortTable(
        table,
        columnIndex
      );
    }

    header.addEventListener(
      "click",
      activate
    );

    header.addEventListener(
      "keydown",
      activate
    );
  }

  function enhanceTable(table) {
    if (!table?.tHead) return;

    /*
      Don't repeatedly initialize the same table.
    */

    if (
      table.dataset.hammerSortable === "true"
    ) {
      return;
    }

    const headerRow =
      table.tHead.rows?.[0];

    if (!headerRow) return;

    const bodyRows =
      Array.from(
        table.tBodies?.[0]?.rows ?? []
      );

    if (!bodyRows.length) return;

    table.classList.add(
      "hammer-sortable-table"
    );

    Array.from(
      headerRow.cells
    ).forEach(
      (header, columnIndex) => {
        makeHeaderSortable(
          table,
          header,
          columnIndex
        );
      }
    );

    table.dataset.hammerSortable =
      "true";
  }

  function enhanceTables(root = document) {
    root
      .querySelectorAll(TABLE_SELECTOR)
      .forEach(enhanceTable);
  }

  function observeTables() {
    const targets = [
      document.getElementById(
        "ratings-container"
      ),
      document.getElementById(
        "view-portal"
      ),
      document.getElementById(
        "view-variance"
      )
    ].filter(Boolean);

    targets.forEach(target => {
      const observer =
        new MutationObserver(() => {
          window.requestAnimationFrame(
            () => enhanceTables(document)
          );
        });

      observer.observe(
        target,
        {
          childList: true,
          subtree: true
        }
      );
    });
  }

  function start() {
    installStyles();
    enhanceTables(document);
    observeTables();

    /*
      Extra passes cover tables rendered
      after data finishes loading.
    */

    window.setTimeout(
      () => enhanceTables(document),
      250
    );

    window.setTimeout(
      () => enhanceTables(document),
      1000
    );
  }

  document.addEventListener(
    "hammer:data-ready",
    () => {
      window.requestAnimationFrame(
        () => enhanceTables(document)
      );
    }
  );

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
