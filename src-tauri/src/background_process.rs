use std::{ffi::OsStr, process::Command};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Capture a console program's output without opening a Windows console window.
pub(crate) fn background_command(program: impl AsRef<OsStr>) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}
