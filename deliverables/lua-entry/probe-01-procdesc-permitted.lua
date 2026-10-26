-- probe 01: is the procdesc (pdfork) syscall family permitted inside the PS4-compat sandbox?
--
-- Deliberately non-destructive: it never forks. pdfork would create a child that keeps running the
-- engine's Lua, which risks taking the game down before we learn anything. pdgetpid/pdkill on an invalid
-- descriptor only answer one question - does the kernel reach the handler at all, or does the sandbox kill
-- the call? That distinction decides whether CVE-2026-45251 is reachable from here.
function main()
    syscall.resolve({
        pdgetpid = 545,
        pdkill   = 546,
        write    = 4,
    })

    local pidp = memory.alloc(8)
    memory.write_qword(pidp, 0)

    -- An invalid fd must fail with EBADF (-1), not kill the process.
    local r1 = syscall.pdgetpid(-1, pidp)
    print("pdgetpid(-1) = " .. tostring(r1) ..
          "  pid=" .. hex(memory.read_qword(pidp)))

    -- Signal 0 on an invalid fd: same expectation.
    local r2 = syscall.pdkill(-1, 0)
    print("pdkill(-1,0)  = " .. tostring(r2))

    -- Control: a known-good syscall through the same path, to prove the dispatcher works at all.
    local r3 = syscall.write(1, "dispatch-ok", 11)
    print("write(1,...)  = " .. tostring(r3))

    print("PROBE-01-DONE")
end

main()
