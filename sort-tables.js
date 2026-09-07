REPLACE ONLY THE EXISTING observeProjectionRows() FUNCTION IN sort-tables.js
WITH THIS EXACT VERSION:

function observeProjectionRows() {
  const target =
    document.getElementById(
      "projections-container"
    );

  if (!target) {
    return;
  }

  const observer =
    new MutationObserver(
      mutations => {
        if (decorating) {
          return;
        }

        // IMPORTANT:
        // Only react when the projection board itself is structurally rebuilt
        // (for example app.js replacing/adding game rows).
        //
        // Ignore descendant mutations created by THIS status decorator:
        // score spans, LIVE badges, FINAL labels, secondary text, etc.
        // Reacting to those mutations creates an infinite decorate ->
        // mutate -> observer -> decorate loop that makes the day headers flash.
        const boardStructureChanged =
          mutations.some(
            mutation => {
              const changedNodes = [
                ...Array.from(
                  mutation.addedNodes || []
                ),
                ...Array.from(
                  mutation.removedNodes || []
                )
              ];

              return changedNodes.some(
                node => {
                  if (
                    !(node instanceof Element)
                  ) {
                    return false;
                  }

                  if (
                    node.matches?.(
                      "tr.game-row, .projection-table"
                    )
                  ) {
                    return true;
                  }

                  return Boolean(
                    node.querySelector?.(
                      "tr.game-row"
                    )
                  );
                }
              );
            }
          );

        if (
          boardStructureChanged
        ) {
          queueProjectionDecoration();
        }
      }
    );

  observer.observe(
    target,
    {
      childList: true,
      subtree: true
    }
  );
}
