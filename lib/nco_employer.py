"""
Created: Camden Opfer, November 2026

Creates jobs that use NCO to manipulate netCDF files. It gives NCO a job, so it's an "employer". Haha! Ha! ha...
"""

ncoComponentToModel = {'atm':'cam', 'lnd':'clm2', 'ocn':'pop', 'ice':'cism'} # From NCO documentation for ncclimo -m option, acceptable options are 'cam','clm2','ocn','ice','cism','cice','pop'. Use CESM2 options here.

def ncoPostprocess(archiveRoots:str|list[str], variables:str|list[str], component:str='atm', histIndex:int=0, yearRange:tuple[int, int]|None=None, makeClimo=True):
    """
    Uses NCO's ncrcat (https://nco.sourceforge.net/nco.html#ncrcat-netCDF-Record-Concatenator) to concatenate CESM output into timeseries files, writing them to the same directory/named file that ADF would to avoid duplication. Optionally, use NCO's ncclimo (https://nco.sourceforge.net/nco.html#ncclimo-netCDF-Climatology-Generator-1) to create climatology files for the same dataset.

    :param archiveRoots: An archive directory, or list of archive directories, to create timeseries for. If a list is provided, a timeseries will be created for each case. Paths are likely of the form "/scratch/$USER/cesm/output/archive/$CASE"
    :type archiveRoots: str or list[str]
    :param variables: A NetCDF variable, or list of variables, of which timeseries will be generated. For example, "TREFHT" or "Q".
    :type variables: str or list[str]
    :param component: The three-letter abbreviation for the model component in which all variables must be stored. For example, "atm" or "lnd". Corresponds with a subdirectory of archiveDirectories. Default is "atm".
    :type component: str, optional
    :param histIndex: The index of history file from which to source data. Files will match the form "*.h{histIndex}.*"
    :type histIndex: int, optional
    :param yearRange: The subset of data to use. Must be a tuple of integers with the second number greater than the first. If data is only found for a subset of that range, then only that subset will be included. Default is None, which uses all available data.
    :type yearRange: tuple[int, int] or None, optional
    :param makeClimo: Whether or not to make a climatology file.
    :type makeClimo: bool, optional
    """
    import os
    from math import ceil
    from warnings import warn
    from glob import glob
    import numpy as np
    from .utils import sbatchTemplate, log, listModuleDeps

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
    ntasks = varCount * len(archiveRoots) * (makeClimo + 1)
    nodeName = os.uname().nodename
    if 'tri' in nodeName:
        # Trillium: 192 cores/node, 4GB/core, full nodes required for jobs
        cpuPerTask = 8
        nodes = ceil(ntasks * cpuPerTask/192)
        sbatchArgs = {'nodes':str(nodes)}
    elif 'fc' in nodeName:
        # Fir: 192 cores/node, 4GB/core
        # Follow performance tuning recommendations from https://docs.alliancecan.ca/wiki/Fir#:~:text=Performance%20tuning%20recommendations
        cpuPerTask = 8
        sbatchArgs = {'ntasks':str(ntasks), 'cpus-per-task':str(cpuPerTask)}
    else:
        warn(f'Unkown node name {nodeName}. Will assume that 8 cpus-per-task and 4GB memory per node is usable on this system.', UserWarning)
        cpuPerTask = 8
        sbatchArgs = {'ntasks':str(ntasks), 'cpus-per-task':str(cpuPerTask), 'mem-per-cpu':'4GB'}

    ## Create, fill out SBATCH script
    if makeClimo:
        jobName = f'ncrcat-ncclimo_{niceVars}'
    else:
        jobName = f'ncrcat_{niceVars}'
    sbatchTemplate(shellScriptPath, jobName, sbatchArgs)

    loadNcoCommand, _ = listModuleDeps('nco')
    with open(shellScriptPath, 'a', encoding='UTF-8') as f:
        f.write(loadNcoCommand)

    # NCO options are documented at https://nco.sourceforge.net/nco.html
    # -c specifies the number of CPUs to run this process on; -O overwwrites existing files, ensuring the desired parameters are used; -4 creates a NetCDF4 files; -h adds metadata about how the file was created; --no_cll_mth removes unnecessary metadata since -h is used
    ncrcatBase = f'srun -c {cpuPerTask} ncrcat -O -4 -h --no_cll_mth '
    # -j specifies the number of tasks to perform simultaneously, ideally 12 so that each month can be averaged simultaneously, though that uses a lot of resources; -4 creates a NetCDF4 files; -h specifies the history file index/number used; -m specifies the model abbreviation in the input, which must be in ['cam','clm2','ocn','ice','cism','cice','pop']; -C specifies the type of climatology, with mth corresponding to monthly; --ypf specifies the maximum number of years included in each climatology file, so that any surplus will be split into new files.
    # NOTE ncclimo has the -p option to specify "backgroun-mode" or MPI parallelism. This is important to job creation, since MPI requires --ntasks and --cpus-per-task arguments to be provided.
    ncclimoBase = f'srun -j 12 ncclimo -4 -h h{histIndex} -m  -C mth --ypf 50'

    def addNcrcat(cmdVariable, cmdInPaths, cmdOutPath):
        with open(shellScriptPath, 'a', encoding='UTF-8') as f:
            f.write(ncrcatBase + f'-v {cmdVariable} {cmdInPaths} -o {cmdOutPath} &')

    def addNcclimo(cmdVariables, startYear, endYear):
        case = os.path.basename(archiveRoot)
        climoOutDir = os.path.join(archiveRoot,'proc', 'climo')

        with open(shellScriptPath, 'a', encoding='UTF-8') as f:
            # NOTE Current way of setting startYear and endYear requires data to start in January of start year and extend through December of endYear. Could throw errors if a run ends partway through a year.
            f.write(ncclimoBase + f'-c {case} -v {cmdVariables} -s {startYear} -e {endYear} -i {archiveRoot} -o {climoOutDir} &')

    # In file name example NdgParams_Ctrl_NoCrop.cam.h0.0001-01.nc
    # Out file name example NdgParams_Ctrl_NoCrop.cam.h0.FLNT.002001-004912.nc
    for archiveRoot in archiveRoots:
        inPaths = glob(os.path.join(archiveRoot, component, 'hist', f'*.h{histIndex}.*.nc'))
        caseName, _, _, _, _ = inPaths[0].split('.')

        inPaths.sort()
        if yearRange is None:
            # Deduce the range of years for use in ncclimo
            _, _, _, startTime, _ = inPaths[0].split('.')
            _, _, _, endTime, _ = inPaths[-1].split('.')
            archiveYearRange = (startTime[:4], endTime[:4])
        else:
            # Mask inPaths to provided year range
            pathSortingHelper = np.strings.partition(inPaths, f'h{histIndex}.')[2] # Will be an array with elements of the form "YYYY*.nc". Here, * may be empty or be something like "-MM-DD".
            yearMask = np.logical_and(pathSortingHelper > f'{yearRange[0]}:04', pathSortingHelper < f'{yearRange[1]}:04')
            inPaths = inPaths[yearMask]
            archiveYearRange = yearRange

        for variable in variables:
            outPath = os.path.join(archiveRoot, component, 'proc', 'tseries', f'{caseName}.{component}.h{histIndex}.{variable}.{archiveYearRange[0]}-{archiveYearRange[1]}.nc')
            # TODO Add checks for output file existing? Or at least a job working on it (see NCO docs about temp files, maybe check for one)? Also could be useful to merge with other files if they have overlapping year ranges
            addNcrcat(variable, inPaths, outPath)

        if makeClimo:
            climoVariables = variables.join(',')
            addNcclimo(climoVariables, archiveYearRange[0], archiveYearRange[1])

    with open(shellScriptPath, 'a', encoding='UTF-8') as f:
        f.write('wait')

    log(f'Run the command:\nsbatch {shellScriptPath}\nTo create the requested timeseries of {component} output.')
