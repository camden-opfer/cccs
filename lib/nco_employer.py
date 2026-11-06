"""
Created: Camden Opfer, November 2026

Creates jobs that use NCO to manipulate netCDF files. It gives NCO a job, so it's an "employer". Haha! Ha! ha...
"""

def tseries(archiveRoots:str|list[str], variables:str|list[str], component:str='atm', hNum:int=0):
    """
    Uses NCO's ncrcat (https://nco.sourceforge.net/nco.html#ncrcat-netCDF-Record-Concatenator) to concatenate CESM output into timeseries files, writing them to the same directory/named file that ADF would to avoid duplication.
    """
    import os
    from math import ceil
    from warnings import warn
    from glob import glob
    from .utils import sbatchTemplate, log

    if isinstance(archiveRoots, str):
        archiveRoots = [archiveRoots]
    if isinstance(variables, str):
        variables = [variables]

    ## Construct shellScriptPath
    shellScriptPath = os.path.join(archiveRoots[0], component, 'generate_tseries.sh')
    shellScriptExists = os.path.exists(shellScriptPath)
    i = 1
    while shellScriptExists and i < 100:
        shellScriptPath = os.path.join(archiveRoots[0], component, f'generate_tseries_{i}.sh')
        shellScriptExists = os.path.exists(shellScriptPath)
        i += 1

    ## Construct niceVars
    varCount = len(variables)
    if varCount == 1:
        niceVars = variables[0]
    elif varCount == 2:
        niceVars = f'{variables[0]}-{variables[1]}'
    else:
        niceVars = f'{variables[0]}-{variables[1]}-etc'

    ## Construct sbatchArgs
    ntasks = varCount * len(archiveRoots)
    nodeName = os.uname().nodename
    if 'tri' in nodeName:
        # Trillium: 192 cores/node, 4GB/core
        nodes = ceil(ntasks * 8/192)
        sbatchArgs = {'nodes':str(nodes)}
        cpuPerTask = 8
    elif 'fc' in nodeName:
        # Fir: 192 cores/node, 4GB/core
        # Follow performance tuning recommendations from https://docs.alliancecan.ca/wiki/Fir#:~:text=Performance%20tuning%20recommendations
        sbatchArgs = {'ntasks':str(ntasks), 'cpus-per-task':'8'}
        cpuPerTask = 8
    else:
        warn(f'Unkown node name {nodeName}. Will assume that 8 cpus-per-task and 4GB memory per node is usable on this system.', UserWarning)
        sbatchArgs = {'ntasks':str(ntasks), 'cpus-per-task':'8', 'mem-per-cpu':'4GB'}
        cpuPerTask = 8

    ## Create, fill out SBATCH script
    sbatchTemplate(shellScriptPath, f'ncrcat_{niceVars}', sbatchArgs)
    with open(shellScriptPath, 'a', encoding='UTF-8') as f:
        f.write('module load StdEnv/2023 gcc/TODO nco/5.4.1')

    # ncrcat options are documented at https://nco.sourceforge.net/nco.html
    # -O overwwrites existing files, ensuring the desired parameters are used; -4 creates a NetCDF4 files; -h adds metadata about how the file was created; --no_cll_mth removes unnecessary metadata since -h is used
    ncrcatBase = f'srun -c {cpuPerTask} ncrcat -O -4 -h --no_cll_mth '
    def addCommand(cmdVariable, cmdInPaths, cmdOutPath):
        with open(shellScriptPath, 'a', encoding='UTF-8') as f:
            f.write(ncrcatBase + f'-v {cmdVariable} {cmdInPaths} -o {cmdOutPath} &')

    # In file name example NdgParams_Ctrl_NoCrop.cam.h0.0001-01.nc
    # Out file name example NdgParams_Ctrl_NoCrop.cam.h0.FLNT.002001-004912.nc
    for archiveRoot in archiveRoots:
        inPaths = glob(os.path.join(archiveRoot, component, 'hist', f'*.h{hNum}.*.nc'))
        inPaths.sort()
        # TODO Weed out any paths that are unneeded, like if they are outside of a requested time range
        caseName, compModel, h, startTime, _ = inPaths[0].split('.')
        _, _, _, endTime, _ = inPaths[-1].split('.')
        startTime = startTime.split('-').join('')[:6]
        endTime = endTime.split('-').join('')[:6]
        for variable in variables:
            outPath = os.path.join(archiveRoot, component, 'proc', 'tseries', f'{caseName}.{compModel}.{h}.{variable}..nc')
            # TODO Add checks for output file existing? Or at least a job working on it (see NCO docs about temp files, maybe check for one?)
            addCommand(variable, inPaths, outPath)

    log(f'Run the command:\nsbatch {shellScriptPath}\nTo create the requested timeseries of {component} output.')
