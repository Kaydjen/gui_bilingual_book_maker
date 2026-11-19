import QtQuick
import Novel
import Shell

// The main window's content with the real view-models (tests/shellfactory.py). `fake.forceButtons` shows the title buttons.
ShellRoot {
    app: appVm
    vm: settingsVm
    log: logVm
    frame: frameVm
    shell: shellVm
    books: booksVm
    add: addVm
    reader: readerVm
    terms: termsVm
    forceButtons: fake.forceButtons === true
}
