@echo off
rem Example startup script for Clink.
rem This is for startup ordering only. Do not use "cls" before prompt initialization
rem if your prompt theme expects the shell startup banner or prompt state.

rem Prefer disabling the default cmd.exe banner via:
rem   clink set clink.logo none
rem or:
rem   clink set clink.logo short

rem If you still want a final clear after prompt setup, do it after the theme is active.
rem Example:
rem   cls
rem
rem But be careful: some prompt themes expect the initial prompt state to be rendered
rem once before a manual clear. Running cls too early can break formatting.

rem Add your own startup commands here.
