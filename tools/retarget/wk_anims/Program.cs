// Cooks a WolvenKit-schema animset glb into an existing .anims -- the GUI's "Import as Anims, use
// existing file". WolvenKit.CLI's import always reads a glb as a mesh, so this calls the importer the
// GUI uses, ModTools.ImportAnims, inside WolvenKit's own install.
//
// Usage: WkAnims <in.anims.glb> <container.anims> <rigs.archive | game dir> [<WolvenKit CLI dir>]
//        WkAnims --list <pairs.tsv> <rigs.archive | game dir> [<WolvenKit CLI dir>]   one "glb<TAB>container" per line
// The container is rewritten in place; its rig decides which skeleton the clips are cooked onto. The importer only
// looks that rig up, so an archive of our rigs (skyrim_port.py's rigs.archive) stands in for the game's, loaded in a
// second; a game dir loads every game and mod archive instead.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;

static class Program
{
    // Parallel cooks start together: one copies, the others find the file there or mid-copy and go on.
    static void CopyOnce(string from, string to)
    {
        if (File.Exists(to)) return;
        try { File.Copy(from, to); }
        catch (IOException) when (File.Exists(to)) { }
    }

    static int Main(string[] args)
    {
        if (args.Length < 3)
        {
            Console.Error.WriteLine("usage: WkAnims <in.anims.glb> <container.anims> <game dir> [<WolvenKit CLI dir>]");
            return 2;
        }
        var wk = args.Length > 3 ? args[3] : Environment.GetEnvironmentVariable("NCN_WOLVENKIT_DIR");
        if (string.IsNullOrEmpty(wk))
        {
            Console.Error.WriteLine("no WolvenKit CLI dir: pass it as the 4th argument or set NCN_WOLVENKIT_DIR");
            return 2;
        }
        var rigs = args[2].EndsWith(".archive", StringComparison.OrdinalIgnoreCase) ? args[2] : null;
        var exe = rigs == null ? Path.Combine(args[2], "bin", "x64", "Cyberpunk2077.exe") : null;
        var pairs = args[0] == "--list"
            ? File.ReadAllLines(args[1]).Where(l => l.Trim().Length > 0).Select(l => l.Split('\t')).ToArray()
            : new[] { new[] { args[0], args[1] } };
        if (pairs.Any(p => p.Length != 2)) { Console.Error.WriteLine("a --list line is not glb<TAB>container"); return 2; }
        foreach (var p in pairs.SelectMany(x => x).Concat(new[] { rigs ?? exe, Path.Combine(wk, "WolvenKit.Modkit.dll") }))
            if (!File.Exists(p)) { Console.Error.WriteLine("not found: " + p); return 2; }

        // The CLI host reads appsettings.json beside the running exe and fails without it.
        CopyOnce(Path.Combine(wk, "appsettings.json"), Path.Combine(AppContext.BaseDirectory, "appsettings.json"));
        // Buffers are Oodle-compressed; without the game's own library WolvenKit falls back to Kraken.
        // A rigs.archive cook has no exe: NCN_GAME_DIR names the game (Windows; Linux has Kraken only).
        var gameBin = exe != null ? Path.GetDirectoryName(exe)
            : Environment.GetEnvironmentVariable("NCN_GAME_DIR") is string g ? Path.Combine(g, "bin", "x64") : null;
        if (gameBin != null && OperatingSystem.IsWindows())
            CopyOnce(Path.Combine(gameBin, "oo2ext_7_win64.dll"), Path.Combine(AppContext.BaseDirectory, "oo2ext_7_win64.dll"));

        var alc = new WolvenKitContext(wk);
        Assembly Load(string name) => alc.LoadFromAssemblyPath(Path.Combine(wk, name + ".dll"));
        var modkit = Load("WolvenKit.Modkit");
        var common = Load("WolvenKit.Common");
        var cli = Load("WolvenKit.CLI");
        var hosting = Load("Microsoft.Extensions.Hosting.Abstractions");

        var builder = cli.GetType("WolvenKit.CLI.GenericHost").GetMethod("CreateHostBuilder")
            .Invoke(null, new object[] { Array.Empty<string>() });
        var host = hosting.GetType("Microsoft.Extensions.Hosting.IHostBuilder").GetMethod("Build").Invoke(builder, null);
        var services = (IServiceProvider)hosting.GetType("Microsoft.Extensions.Hosting.IHost")
            .GetProperty("Services").GetValue(host);

        // The importer resolves the container's rig through the archives loaded as the base game's.
        var archiveType = common.GetType("WolvenKit.Common.IArchiveManager");
        var archives = services.GetService(archiveType);
        if (rigs != null)
        {
            var loadArchive = archiveType.GetMethod("LoadArchive");
            var source      = Enum.Parse(loadArchive.GetParameters()[1].ParameterType, "Base");
            loadArchive.Invoke(archives, new object[] { Path.GetFullPath(rigs), source });
        }
        else
            archiveType.GetMethod("Initialize").Invoke(archives, new object[] { new FileInfo(exe), false });

        var modTools = services.GetService(common.GetType("WolvenKit.Common.Interfaces.IModTools"));
        var importArgsType = common.GetType("WolvenKit.Common.Model.Arguments.GltfImportArgs");
        var importArgs = Activator.CreateInstance(importArgsType);
        importArgsType.GetProperty("ImportFormat").SetValue(importArgs,
            Enum.Parse(common.GetType("WolvenKit.Common.Model.Arguments.GltfImportAsFormat"), "Anims"));
        var import = modkit.GetType("WolvenKit.Modkit.RED4.ModTools").GetMethods()
            .Single(m => m.Name == "ImportAnims" && m.GetParameters()[0].ParameterType == typeof(FileInfo));

        var failed = 0;
        foreach (var p in pairs)
        {
            using var stream = new FileStream(p[1], FileMode.Open, FileAccess.ReadWrite);
            var ok = (bool)import.Invoke(modTools, new object[] { new FileInfo(p[0]), stream, importArgs });
            Console.WriteLine(ok ? "cooked " + p[1] : "ImportAnims refused " + p[0]);
            if (!ok) failed++;
        }
        if (pairs.Length > 1) Console.WriteLine("{0} of {1} cooked", pairs.Length - failed, pairs.Length);
        return failed == 0 ? 0 : 1;
    }
}

// WolvenKit ships System.Text.Json 9 and friends; the default context would bind the runtime's own.
sealed class WolvenKitContext : AssemblyLoadContext
{
    readonly string dir;
    public WolvenKitContext(string dir) : base("wolvenkit") { this.dir = dir; }

    protected override Assembly Load(AssemblyName name)
    {
        var path = Path.Combine(dir, name.Name + ".dll");
        return File.Exists(path) ? LoadFromAssemblyPath(path) : null;
    }

    protected override IntPtr LoadUnmanagedDll(string name)
    {
        // kraken.dll on Windows, libkraken.so elsewhere (WolvenKit.Core ships both)
        var stem = name.EndsWith(".dll") ? name[..^4] : name;
        var path = Path.Combine(dir, OperatingSystem.IsWindows() ? stem + ".dll" : "lib" + stem + ".so");
        return File.Exists(path) ? LoadUnmanagedDllFromPath(path) : IntPtr.Zero;
    }
}
