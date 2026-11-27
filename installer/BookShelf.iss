#include "version.iss"

; 中文语言文件随 Inno Setup 的 Languages 目录分发；缺失时回退英文，保证脚本可编译。
#define ChineseISL AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl"
#if FileExists(ChineseISL)
#define HasChineseLanguage
#endif

[Setup]
AppId={{8F3C2A11-5B7D-4E9A-9C21-BOOKSHELF0001}}
AppName=BookShelf
AppVersion={#AppVersion}
AppVerName=BookShelf {#AppVersion}
AppPublisher=BookShelf contributors
VersionInfoVersion={#AppVersionQuad}
VersionInfoProductVersion={#AppVersionQuad}
DefaultDirName={localappdata}\Programs\BookShelf
DefaultGroupName=BookShelf
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsePreviousAppDir=yes
CloseApplications=yes
; 安装结束后不再让 Setup 自动重启 BookShelf：Qt WebEngine 的子进程会让
; 完成页等待或与已运行的实例争抢单实例锁，表现为点击“完成”无响应。
RestartApplications=no
SetupIconFile=..\app\ui\resources\app.ico
UninstallDisplayIcon={app}\BookShelf.exe
UninstallDisplayName=BookShelf
LicenseFile=..\LICENSE
OutputDir=..\release
OutputBaseFilename=BookShelf-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
#ifdef HasChineseLanguage
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Messages]
#ifdef HasChineseLanguage
chinesesimplified.FinishedLabel=安装完成。%n%n书库、设置与阅读进度保存在 %APPDATA%\BookShelf，卸载 BookShelf 不会删除该目录。%n%n点击“完成”退出安装程序。
#else
english.FinishedLabel=Setup has finished installing [name] on your computer.%n%nYour library, settings and reading progress are stored in %APPDATA%\BookShelf. Uninstalling BookShelf keeps this data directory.%n%nClick Finish to exit Setup.
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "contextmenu"; Description: "在电子书右键菜单中添加“用 BookShelf 阅读”"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\BookShelf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 1.1.2 及更早版本把依赖放在 _internal；升级到平铺布局时清掉旧目录，避免遗留近 400 MB 文件。
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\BookShelf"; Filename: "{app}\BookShelf.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 BookShelf"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BookShelf"; Filename: "{app}\BookShelf.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; “打开方式”候选，不抢占用户已有的默认打开程序。
Root: HKCU; Subkey: "Software\Classes\BookShelf.ebook"; ValueType: string; ValueName: ""; ValueData: "BookShelf 电子书"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\BookShelf.ebook\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\BookShelf.exe,0"
Root: HKCU; Subkey: "Software\Classes\BookShelf.ebook\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\BookShelf.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "书库助手 BookShelf"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\BookShelf.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "BookShelf.ebook"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "BookShelf.ebook"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mobi\OpenWithProgids"; ValueType: string; ValueName: "BookShelf.ebook"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.azw3\OpenWithProgids"; ValueType: string; ValueName: "BookShelf.ebook"; ValueData: ""; Flags: uninsdeletevalue

; 可选的右键菜单，仅在用户勾选 contextmenu 任务时创建。
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\BookShelfRead"; ValueType: string; ValueName: ""; ValueData: "用 BookShelf 阅读"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\BookShelfRead"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\BookShelf.exe,0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.epub\shell\BookShelfRead\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\BookShelfRead"; ValueType: string; ValueName: ""; ValueData: "用 BookShelf 阅读"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\BookShelfRead"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\BookShelf.exe,0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\BookShelfRead\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mobi\shell\BookShelfRead"; ValueType: string; ValueName: ""; ValueData: "用 BookShelf 阅读"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mobi\shell\BookShelfRead"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\BookShelf.exe,0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mobi\shell\BookShelfRead\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.azw3\shell\BookShelfRead"; ValueType: string; ValueName: ""; ValueData: "用 BookShelf 阅读"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.azw3\shell\BookShelfRead"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\BookShelf.exe,0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.azw3\shell\BookShelfRead\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BookShelf.exe"" ""%1"""; Tasks: contextmenu

[UninstallDelete]
; 只清理程序目录；%APPDATA%\BookShelf 不在卸载删除范围内。
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty; Name: "{app}"
