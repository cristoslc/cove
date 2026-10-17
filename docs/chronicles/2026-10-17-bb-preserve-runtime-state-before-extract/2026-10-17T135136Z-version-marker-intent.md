# Safely validate the retained extraction marker

Per operator request: because `.version` now remains in place until bundle copying succeeds, validate its existing type through a no-follow nonblocking descriptor and replace it atomically only after successful copying. Add symlink/FIFO regressions so metadata cannot redirect a write or hang extraction. Keep work limited to the resource updater and temp-root tests; the required full gate stays pending recovery completion.
