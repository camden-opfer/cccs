"""
Created: Camden Opfer, November 2026

Creates jobs that use NCO to manipulate netCDF files. It gives NCO a job, so it's an "employer". Haha! Ha! ha...
"""

def tseries(archiveRoots:str|list[str], variables:str|list[str], component:str='atm', histIndex:int=0, makeClimo=True):
    """
    Uses NCO's ncrcat (https://nco.sourceforge.net/nco.html#ncrcat-netCDF-Record-Concatenator) to concatenate CESM output into timeseries files, writing them to the same directory/named file that ADF would to avoid duplication.

    :param archiveRoots: An archive directory, or list of archive directories, to create timeseries for. If a list is provided, a timeseries will be created for each case. Paths are likely of the form "/scratch/$USER/cesm/output/archive/$CASE"
    :type archiveRoots: str or list[str]
    :param variables: A NetCDF variable, or list of variables, of which timeseries will be generated. For example, "TREFHT" or "Q".
    :type variables: str or list[str]
    :param component: The three-letter abbreviation for the model component in which all variables must be stored. For example, "atm" or "lnd". Corresponds with a subdirectory of archiveDirectories. Default is "atm"
    :type component: str
    :param histIndex: The index of history file from which to source data. Files will match the form "*.h{histIndex}.*"
    :type histIndex: int
    :param makeClimo: Whether or not to make a climatology.
    :type makeClimo: bool
    """
    import os
    from math import ceil
    from warnings import warn
    from glob import glob
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
    if makeClimo:
        jobName = f'ncrcat-ncclimo_{niceVars}'
    else:
        jobName = f'ncrcat_{niceVars}'
    sbatchTemplate(shellScriptPath, jobName, sbatchArgs)

    loadNcoCommand, _ = listModuleDeps('nco')
    with open(shellScriptPath, 'a', encoding='UTF-8') as f:
        f.write(loadNcoCommand)

    # ncrcat options are documented at https://nco.sourceforge.net/nco.html
    # -O overwwrites existing files, ensuring the desired parameters are used; -4 creates a NetCDF4 files; -h adds metadata about how the file was created; --no_cll_mth removes unnecessary metadata since -h is used
    ncrcatBase = f'srun -c {cpuPerTask} ncrcat -O -4 -h --no_cll_mth '
    ncclimoBase = f'srun -c {cpuPerTask} ncclimo' # TODO Complete this based on https://nco.sourceforge.net/nco.html#ncclimo-netCDF-Climatology-Generator-1

    if makeClimo:
        def addCommand(cmdVariable, cmdInPaths, cmdOutPath):
            with open(shellScriptPath, 'a', encoding='UTF-8') as f:
                f.write(ncrcatBase + f'-v {cmdVariable} {cmdInPaths} -o {cmdOutPath} &')
                f.write(ncclimoBase + f'-c {$CASE} -s {srt_yr} -e {end_yr} -i {inDir} -o {outDir} &') # TODO Make this functional!!

    else:
        def addCommand(cmdVariable, cmdInPaths, cmdOutPath):
                    with open(shellScriptPath, 'a', encoding='UTF-8') as f:
                        f.write(ncrcatBase + f'-v {cmdVariable} {cmdInPaths} -o {cmdOutPath} &')

    # In file name example NdgParams_Ctrl_NoCrop.cam.h0.0001-01.nc
    # Out file name example NdgParams_Ctrl_NoCrop.cam.h0.FLNT.002001-004912.nc
    for archiveRoot in archiveRoots:
        inPaths = glob(os.path.join(archiveRoot, component, 'hist', f'*.h{histIndex}.*.nc'))
        inPaths.sort()
        # TODO Weed out any paths that are unneeded, like if they are outside of a requested time range
        caseName, compModel, h, startTime, _ = inPaths[0].split('.')
        _, _, _, endTime, _ = inPaths[-1].split('.')
        startTime = startTime.split('-').join('')[:6]
        endTime = endTime.split('-').join('')[:6]
        for variable in variables:
            outPath = os.path.join(archiveRoot, component, 'proc', 'tseries', f'{caseName}.{compModel}.{h}.{variable}.nc')
            # TODO Add checks for output file existing? Or at least a job working on it (see NCO docs about temp files, maybe check for one?)
            addCommand(variable, inPaths, outPath)

    log(f'Run the command:\nsbatch {shellScriptPath}\nTo create the requested timeseries of {component} output.')

def old_avgOverTime(cesmOutRoot:str, archive:bool = True, varNames:list[str]|None=None, component:str = 'cam', fileType:str = 'h0', years:list[str]|None=None, months:list[str]|None=None, days:list[str]|None=None, seconds:list[str]|None = None, ncoOutputRoot:str|None = None, operation:str|None = None) -> str:
    """
    Uses getPaths() to find paths corresponding to a time period and then uses nco.ncra to place an average over them in a file specified by ncoPath(). If the averaged file corresponding to the provided cesmOutRoot, component, and time arguments already exists, variables which do not yet have data are appended to the file, while others are skipped for speed. Returns the path to the netCDF file containing the relevant data.

    :param cesmOutRoot: A directory with CESM output. Often of the form "/scratch/$USER/cesm/output/archive/$CASE" or, occasionally, "/scratch/$USER/cesm/output/$CASE/run".
    :type cesmOutRoot: str
    :param archive: Whether or not cesmOutRoot leads to an archive directory, which things like lnd/hist subdirectories contain the actual data. If True, assumes that directory structure, and looks for output files accordingly. If False, assumes all data is in cesmOutRoot, and does not do any recursive searching.
    :type archive: bool, optional
    :param varNames: A list containing the subset of variables from the CESM output to include in the output. Default is None, in which case all variables are averaged.
    :type varNames: list[str] or None, optional
    :param component: A string representing the model component to retrieve data from. Commonly will be 'cam', 'clm2', or maybe 'mosart' or 'pop'.
    :type component: str, optional
    :param fileType: Which type of output file for this component to search for. Typically 'h0', maybe 'h1', occasionally 'h2'-'h9' or 'i'. Default is 'h0' because it is most likely to exist. The type 'h0' corresponds to monthly output unless the CESM namelist for component was altered.
    :type fileType: str, optional
    :param years: A list of strings representing the years from which to get output. Each string must have four numerical characters (e.g. '0001') or be some regular expression that will evaluate in that way. Default is None, which will grab all data.
    :type years: list[str] or None, optional
    :param months: A list of strings representing the months from which to get output. Each string must have two numerical characters (e.g. '01') or be some regular expression that will evaluate in that way. Default is None, which will grab all data.
    :type months: list[str] or None, optional
    :param days: A list of strings representing the days from which to get output. Each string must have two numerical characters (e.g. '01') or be some regular expression that will evaluate in that way. Default is None, which will grab all data.
    :type days: list[str] or None, optional
    :param seconds: A list of strings representing the seconds from which to get output. Each string must have five numerical characters (e.g. '000000') or be some regular expression that will evaluate in that way. Default is None, which will grab all data.
    :type seconds: list[str] or None, optional
    :param ncoOutputRoot: The root directory to which the output from NCO operations (like ncra here) should be written. Should be consistent between uses so that this and related functions can find output. Default is None, which uses _ncoOutputRoot, which in turn is set above to be /scratch/$USER/nco.
    :type ncoOutputRoot: str or None, optional
    :param operation: The operation argument to be passed to NCO's ncra. Must be one of 'avg', 'sqravg', 'avgsqr', 'max', 'min', 'mabs', 'mebs', 'mibs', 'rms', 'rmssdn', 'sqrt', 'tabs', and 'ttl', or None. Default is None, in which case ncra performs an arithmetic average (same as passing 'avg').
    :type operation: str or None, optional

    :return: String representing the path to the averaged data
    :rtype: str
    """
    import os
    import numpy as np

    if ncoOutputRoot is None:
        ncoOutputRoot = _ncoOutputRoot
    if operation is None:
        operation = 'avg' # Explicitly set so that the ncoPath reflects that this is using ncra

    ncoOutFile = ncoPath(cesmOutRoot, component, years, months, days, seconds, ncoOutputRoot, operation)

    if not os.path.exists(ncoOutFile):
        cesmOutFiles, dataFrequency = getPaths(cesmOutRoot, archive, component, fileType, years, months, days, seconds)

        ncoOptions = ['-A'] # -A = append, so will add any variables that don't exist in ncoOutFile, but otherwise leave it be
        ncoKwargs = {}
        if varNames is not None:
            ncoKwargs['variable'] = ','.join(varNames) # Join will turn a list like ['U','V','T'] into a string like 'U,V,T' as required by the NCO CLI
        if operation in ['avg', 'sqravg', 'avgsqr', 'max', 'min', 'mabs', 'mebs', 'mibs', 'rms', 'rmssdn', 'sqrt', 'tabs', 'ttl']:
            ncoKwargs['operation'] = operation
        else:
            raise ValueError

        if dataFrequency == 'month':
            # NOTE Ignores leap years, though CESM usually does too
            if months is None:
                monthWeights = '31,28,31,30,31,30,31,31,30,31,30,31'
            else:
                monthLengths = np.array(['na','31','28','31','30','31','30','31','31','30','31','30','31']) # Assumes Jan=1, Dec=12 (as required by months argument anyway)
                relevantMonthLengths = monthLengths[months]
                monthWeights = ','.join(relevantMonthLengths.tolist())

            ncoKwargs['weight'] = monthWeights

        nco = Nco()
        nco.ncra(input=cesmOutFiles, output=ncoOutFile, options=ncoOptions, use_shell=True, **ncoKwargs)

    return ncoOutFile
