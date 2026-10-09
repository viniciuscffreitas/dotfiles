// memguard-notify — react to memory pressure the way Apple intends, instead of
// polling a sysctl on a timer.
//
// memguard runs from launchd every 30 s. A 30 s poll is fine for a slow drift
// and useless for a fast one: a build can take the machine from comfortable to
// thrashing inside a single interval. The kernel already publishes the event,
// and libdispatch exposes it as DISPATCH_SOURCE_TYPE_MEMORYPRESSURE, the same
// signal Activity Monitor colours green, yellow and red. This process blocks on
// that source, consumes no CPU while nothing happens, and runs memguard the
// instant the level changes. The 30 s poll stays as a backstop, because the
// dispatch source fires on transitions, not on a level that stays bad.
//
// Build: clang -O2 -Wall -o ~/dotfiles/bin/memguard-notify memguard-notify.c

#include <dispatch/dispatch.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static const char *kMemguard = "/Users/vini/dotfiles/bin/memguard";

static void run_memguard(const char *why) {
    // memguard keeps its own cooldown, so firing it repeatedly is safe.
    fprintf(stderr, "memguard-notify: %s\n", why);
    fflush(stderr);
    pid_t pid;
    char *const argv[] = {(char *)kMemguard, NULL};
    if (posix_spawn(&pid, kMemguard, NULL, NULL, argv, environ) == 0) {
        int st;
        waitpid(pid, &st, 0);
    } else {
        perror("posix_spawn");
    }
}

int main(void) {
    signal(SIGCHLD, SIG_DFL);
    dispatch_queue_t q = dispatch_queue_create("memguard.notify", DISPATCH_QUEUE_SERIAL);
    dispatch_source_t src = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_MEMORYPRESSURE, 0,
        DISPATCH_MEMORYPRESSURE_WARN | DISPATCH_MEMORYPRESSURE_CRITICAL, q);
    if (!src) {
        fprintf(stderr, "memguard-notify: could not create the memory pressure source\n");
        return 1;
    }
    dispatch_source_set_event_handler(src, ^{
        unsigned long flags = dispatch_source_get_data(src);
        if (flags & DISPATCH_MEMORYPRESSURE_CRITICAL)
            run_memguard("kernel reported CRITICAL pressure");
        else if (flags & DISPATCH_MEMORYPRESSURE_WARN)
            run_memguard("kernel reported WARNING pressure");
    });
    dispatch_activate(src);
    fprintf(stderr, "memguard-notify: subscribed to kernel memory pressure events\n");
    fflush(stderr);
    dispatch_main();
    return 0;
}
